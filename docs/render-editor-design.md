# 成片编辑（导演台）设计草案

> 目标：把现在的「等比缩放 + 硬拼接」升级成可用的**轻量剪辑台**——
> 支持镜头裁剪、转场、BGM、旁白、字幕、片头片尾，并保持一键导出。

---

## 1. 能力边界

**要做（按优先级）**

| 优先级 | 能力 | 说明 |
|---|---|---|
| P0 | 镜头裁剪 | 每镜设入点/出点，去掉首尾多余帧 |
| P0 | BGM | 选素材库音频，设音量、淡入淡出、循环铺满、自动闪避旁白 |
| P0 | 字幕 | 按镜头文案自动生成时间轴，烧录或导出 .srt |
| P1 | 旁白 | 每镜挂一段配音音频；后续接 TTS 自动生成 |
| P1 | 转场 | 淡入淡出 / 交叉溶解，可设时长 |
| P1 | 片头片尾 | 纯色卡 + 文字，或指定一张图 |
| P2 | 多轨音频 | 多条 BGM / 音效，带独立音量与时间偏移 |
| P2 | 速度调整 | 每镜 0.5x ~ 2x |
| P2 | 响度标准化 | 统一到 -16 LUFS，避免忽大忽小 |

**不做**

- 关键帧动画、多视频轨叠加、调色曲线（这些交给专业 NLE）
- 真正的非线性拖拽时间轴（P2 再考虑，先用列表 + 滑块）

---

## 2. 数据模型

### 2.1 扩展现有 `renders.options`（JSON）

```jsonc
{
  "width": 1280, "height": 720, "fps": 24,
  "transition": { "type": "fade", "duration": 0.4 },   // none|fade|dissolve
  "title": { "text": "雪夜", "duration": 2.0, "bg": "#000" },
  "tail":  { "text": "第一集 完", "duration": 2.0 },
  "bgm": {
    "asset_id": "ast_xxx", "volume_db": -12,
    "fade_in": 1.5, "fade_out": 2.0,
    "loop": true, "duck": true, "duck_db": -14
  },
  "voice": { "volume_db": 0, "normalize": true },
  "subtitles": {
    "enabled": true, "mode": "burn",            // burn | sidecar | both
    "font": "Noto Sans CJK SC", "size": 42,
    "color": "#FFFFFF", "outline": 2, "margin_v": 48,
    "source": "shot_text"                        // shot_text | srt_asset
  },
  "loudness": { "target_lufs": -16, "enabled": true }
}
```

### 2.2 新增表 `render_shots`（每镜编辑参数）

```sql
CREATE TABLE render_shots (
  render_id  TEXT NOT NULL,
  shot_id    TEXT NOT NULL,
  idx        INTEGER NOT NULL,   -- 排序
  in_point   REAL DEFAULT 0,     -- 入点（秒）
  out_point  REAL,               -- 出点（NULL = 到结尾）
  speed      REAL DEFAULT 1.0,
  volume_db  REAL DEFAULT 0,
  muted      INTEGER DEFAULT 0,
  voice_asset TEXT,              -- 该镜旁白
  subtitle   TEXT,               -- 该镜字幕文本（空则用镜头标题/描述）
  PRIMARY KEY (render_id, shot_id)
);
```

> 为什么单独建表：这些参数是「这次成片」的编辑决定，不应回写到镜头本身；
> 同一个镜头可以导出多个版本（不同 BGM / 不同裁剪）。

---

## 3. FFmpeg 流水线

分成 5 个阶段，每阶段更新 `renders.message/progress`，失败保留中间产物便于排查。

```
① 单镜处理 → clip_001.mp4 …
   -ss/-to 裁剪、scale/pad、fps、setsar
   -vf "scale=..,pad=..,fps=..,setpts=PTS/speed"
   -af "atempo=speed,volume=.."
   -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k

② 拼接
   无转场：concat demuxer（最快，-c copy 不行时重编码）
   有转场：filter_complex xfade + acrossfade，offset 累加

③ 音频混音
   BGM: -stream_loop -1 -i bgm → atrim=0:总时长, afade in/out, volume
   闪避: sidechaincompress（旁白为 sidechain，BGM 为被压缩）
   混合: amix=inputs=N:normalize=0，旁白优先

④ 字幕 + 片头片尾
   片头: color/图片 + drawtext，或用 concat 前置一段 2 秒 mp4
   字幕: subtitles=subs.srt:force_style='FontName=...,FontSize=...,Outline=..'
   注意：需要 ffmpeg 编译带 libass；启动时检测，缺失则降级为 sidecar .srt

⑤ 收尾
   loudnorm=I=-16:TP=-1.5:LRA=11
   -movflags +faststart
   抽封面、写 .srt、记录时长
```

### 3.1 能力探测（启动时一次）

```python
ffmpeg -hide_banner -filters | grep -E "subtitles|xfade|sidechaincompress"
ffmpeg -hide_banner -encoders | grep -E "libx264|aac"
```

缺 `libass` → 字幕只能导出 .srt；缺 `xfade` → 转场降级为直接切。

---

## 4. API 设计

```http
POST /api/projects/{pid}/renders
{
  "shot_ids": [...],
  "options": { ...上面的 options... },
  "shot_edits": [
    {"shot_id": "...", "in_point": 0.5, "out_point": 4.8, "volume_db": -3,
     "subtitle": "雪夜，山门前"}
  ]
}
→ { "id": "rnd_...", "status": "queued" }

GET  /api/renders/{id}            # 状态、进度、message、产物
GET  /api/renders/{id}/timeline   # 计算后的每镜时长/起止时间（给 UI 画轴）
POST /api/renders/{id}/preview    # 480p 快速草稿（crf 28，只跑 ①②④ 简化版）
GET  /api/renders/{id}/subtitles  # 下载 .srt
POST /api/renders/{id}/cancel
DELETE /api/renders/{id}
```

旁白（P1）：

```http
POST /api/projects/{pid}/shots/{sid}/narration
{ "text": "……", "voice": "female_01" }
→ 调用 TTS provider，产物登记为 asset，写回 render_shots.voice_asset
```

TTS 先用「接口抽象 + 手动上传」兜底：

```yaml
tts:
  provider: ""          # "" | openai | edge | comfy
  base_url: ""
  api_key: ""
  voice: ""
```

---

## 5. UI 设计（「成片」页）

```
┌──────────────────────────────────────────────────────────────┐
│ 成片工作台      [项目 ▾]                    [预览] [导出成片] │
├──────────────┬───────────────────────────────┬───────────────┤
│ 镜头时间轴    │ 预览播放器                     │ 检查器         │
│ ┌──────────┐ │ ┌───────────────────────────┐ │ 画布           │
│ │▣ 镜头1 3s│ │ │                           │ │  分辨率/帧率   │
│ │▣ 镜头2 5s│ │ │        (video)            │ │ 音频           │
│ │▣ 镜头3 4s│ │ │                           │ │  BGM/音量/淡入 │
│ └──────────┘ │ └───────────────────────────┘ │  旁白/闪避     │
│ 拖动排序      │ 00:03 / 00:12                 │ 字幕           │
│              │                               │  字体/大小/位置│
│              │                               │ 转场/片头片尾  │
└──────────────┴───────────────────────────────┴───────────────┘
```

**关键交互**

- 左侧镜头条目：缩略图、时长、入点/出点双滑块（拖动时实时显示时间）
- 检查器分 4 个折叠组：画布 / 音频 / 字幕 / 转场
- BGM 从素材库选（复用现有 picker），选完显示波形占位 + 时长
- 「预览」生成 480p 草稿，缓存键 = options + shot_edits 的哈希；改参数后需重新点
- 导出时显示分阶段进度：`3/5 段标准化 → 混音 → 字幕 → 收尾`

---

## 6. 落地顺序

| 阶段 | 内容 | 预估 |
|---|---|---|
| **M1** | 单镜裁剪 + 音量 + BGM（含淡入淡出/循环）+ 字幕烧录 + 分阶段进度 | 2~3 天 |
| **M2** | 预览草稿、时间轴接口、转场（xfade）、响度标准化 | 2 天 |
| **M3** | 旁白（上传音频 + 混音 + 闪避）、片头片尾 | 2 天 |
| **M4** | TTS 接入、多 BGM 轨、速度调整 | 3 天 |

**M1 就能解决你现在最想要的三个**：BGM、字幕、镜头裁剪。

---

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| ffmpeg 没编译 libass | 启动探测；缺则字幕降级为 .srt sidecar，并在 UI 提示 |
| 中文字体缺失 | Dockerfile 已有 fonts-dejavu-core；再加 `fonts-noto-cjk`，并允许配置字体文件路径 |
| 长视频导出耗时长（H20 MIG 切片 CPU 弱） | 预览用 480p + crf 28；导出走 `-preset veryfast`；支持取消 |
| 音画不同步（裁剪/变速） | 每镜先统一 fps 与采样率（48kHz），裁剪用 `-ss/-to` 在编码前 |
| BGM 版权 | 只允许从素材库选用户自己上传的音频，不内置曲库 |
| 多次导出占磁盘 | `renders/` 目录按项目配额，UI 可删除历史成片 |

---

## 8. 与现有代码的衔接

| 现有 | 改动 |
|---|---|
| `render.py` | 拆成 `pipeline.py`：clip → concat → audio → subtitle → finalize，每步可单测 |
| `ffmpeg.py` | 增加 `trim_clip`、`mix_audio`、`burn_subtitles`、`loudnorm`、`capabilities()` |
| `renders` 表 | options 已是 JSON，直接扩展；新增 `render_shots` 表（Alembic 迁移） |
| `RenderPanel.tsx` | 改造成三栏工作台；保留旧版「快速导出」入口 |
| 素材库 | BGM/旁白直接复用现有 audio asset，无需新存储 |


---

## 8.1 实现状态（2026-10-20）

| 阶段 | 状态 | 提交 |
|---|---|---|
| M1 逐镜裁剪 / BGM / 字幕 / 响度 / 分阶段进度 | ✅ 已完成 | `3357057` 后端、`7ceba32` 前端 |
| M1 成片工作台 UI | ✅ 已完成 | `7ceba32` |
| M2 预览草稿 / 转场 / 时间轴接口 | ⏳ 待做 | — |
| M3 旁白（上传音频 + 混音 + 闪避） | ⏳ 待做 | — |
| M4 TTS（GPT-SoVITS） | 📝 计划 | 见第 10 节 |

M1 的实际接口：

```http
POST /api/projects/{pid}/renders
{ "shot_ids": [...],
  "options": { "width":..., "height":..., "fps":...,
               "bgm": {...}, "subtitles": {...}, "loudness": {...} },
  "shot_edits": [{"shot_id":..., "in_point":..., "out_point":..., "subtitle":...}] }

GET /api/renders/{id}/subtitles
GET /api/ffmpeg/status      # 含 capabilities
```

实际踩到并修掉的两个坑（写在这里避免重复踩）：

1. SRT 时间轴必须是 `00:00:00,000 --> 00:00:01,800` **一行**，拆两行 libass 会报 “Unable to open”；
2. SRT 用 `utf-8-sig`（带 BOM），否则中文在 Windows 上编码探测失败。

## 9. 已确认的决策（2026-10-20）

| 议题 | 决定 |
|---|---|
| 字幕输出 | **burn + sidecar 都出**（`mode: both`），mp4 能直接播，srt 可二次编辑 |
| 字体 | 本地 Windows 用系统字体；Linux/AutoDL 由 install.py 尝试装 `fonts-noto-cjk`，缺失时 UI 提示 |
| 旁白 | M3 先支持「上传录音」，TTS 留接口到 M4 |
| BGM | 只允许素材库音频（用户自己上传），不内置曲库 |
| ffmpeg | `install.py` 优先下载 **full 版**（BtbN gpl，含 libass/xfade/libx264），失败回退 imageio-ffmpeg；两者都做能力自检 |
| 内网 Dockerfile | 不纳入本项目维护，仅作内网验证 |

### install.py 的 ffmpeg 策略

```
--ffmpeg-source auto | full | system | imageio
auto: 系统 ffmpeg → 下载 full → imageio 兜底
自检：subtitles / xfade / libx264 三项都在才算“完整”
```

---

## 10. M4：接入 GPT-SoVITS（计划，暂不实现）

### 目标

用 GPT-SoVITS 做**角色音色克隆 + 旁白/对白生成**，替代 M3 的手动上传。

### 形态

```
[镜头] → 文案 → (角色音色) → TTS → 音频资产 → 自动挂到 render_shots.voice_asset
```

### 接口设计（先留桩）

```yaml
tts:
  provider: gpt_sovits
  base_url: http://127.0.0.1:9880     # GPT-SoVITS api_v2
  ref_audio: ""                        # 参考音频（音色）
  ref_text: ""                         # 参考音频对应文本（v2 需要）
  prompt_lang: zh
  text_lang: zh
  speed: 1.0
```

```http
POST /api/tts/preview   { text, voice_id }        → wav 片段（试听）
POST /api/tts/voices    { name, ref_audio }       → 新建音色
GET  /api/tts/voices                              → 音色列表
```

### 为什么放 M4

- GPT-SoVITS 需要单独的推理服务（模型几个 GB、要 GPU 或至少 CPU 推理），
  不适合塞进导演台主进程；应作为**外部服务**，导演台只做 HTTP 调用。
- 在 AutoDL 上可以和 ComfyUI 共用同一张卡，但要注意显存争抢（H3 跑完再跑 TTS）。
- 音色一致性是难点：同一角色跨镜头要用同一个 `ref_audio`，否则音色会漂。

### 与剪辑流水线的衔接

`voice_asset` 已经是 `render_shots` 的字段，TTS 只是“把资产造出来”的多一种方式，
剪辑侧不需要改。

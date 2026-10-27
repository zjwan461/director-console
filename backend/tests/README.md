# 导演台回归测试

针对「导演助手」的接口级回归。默认**不调用 ComfyUI**，只有显式加 `--gpu` 才会真实出图/出视频。

## 前置

1. 面板服务在跑：

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 6006
```

2. 依赖：`httpx`（项目已有）。测试用 `data/director.db` 读运行状态，
   也可以用环境变量覆盖：

```powershell
$env:DSH_PANEL = "http://127.0.0.1:6006"
$env:DSH_DB    = "D:\workspaces\minimax\director-console\data\director.db"
```

## 跑法

```powershell
cd backend\tests

python test_corpus.py        # 34 条语料，跳过 4 条 GPU 用例
python test_corpus.py --gpu  # 全量（会真实出图，别在 ComfyUI 忙的时候跑）

python test_step2.py         # 多步计划：拆分 + 一次确认 + 连续执行
python test_chain.py --gpu   # 依赖链：出图 → 自动续跑视频
python test_audio.py         # 音频上传 + 对口型确认卡（不提交 GPU）
python test_audio2.py        # 时长对齐 / 多段参考音频 / 上传音频当 BGM
python test_cancel.py        # 取消确认卡后的回复（不能像要继续）
python test_files_only.py    # 只发图片/音频不说话：应确认收到并记住素材
python test_agent_loop.py    # 规则没覆盖的说法：看状态后能否做对
python test_motion_prompt.py # 图生视频的运镜是否看图生成 + 确认卡标出能力卡
python test_vision.py        # 看图写运镜（i2v/r2v）+ 视觉修订（模糊评价/改画幅）
```

## 覆盖范围

| 文件 | 覆盖 |
|---|---|
| `test_corpus.py` | 生成 / 导出 / 剪辑 / 配乐 / 设置 / 修订 / 指代 / 查询 / 问答 / 项目镜头 / 边界 |
| `test_step2.py` | 复合句拆多步、一次确认、两步连续写入 |
| `test_chain.py` | 依赖步骤延后 + 产物完成后自动续跑 |
| `test_audio.py` | 音频上传、附件进消息、对口型（lipsync）确认卡带参考音频 |
| `test_audio2.py` | 对口型按音频时长出片、多段参考音频、上传音频当 BGM |
| `test_cancel.py` | 取消确认卡后回复为「已取消」且不产生任务 |
| `test_files_only.py` | 只发文件不说话时的确认与素材记忆 |
| `test_agent_loop.py` | agentic 循环：从镜头出视频、查镜头、片子体检、图塞进镜头 |
| `test_motion_prompt.py` | 看图生成运镜提示词、确认卡显示能力卡 |
| `test_vision.py` | i2v/r2v 看图写运镜、模糊修订与改画幅走视觉 |

## 约定

- 所有用例都在 `QA-` 前缀的临时项目里跑，结束时自动删除
- 不需要 GPU 的用例在确认卡处直接取消，不会提交真实任务
- 造历史产物用 `qa.add_artifacts()` 直接写库，不跑生成

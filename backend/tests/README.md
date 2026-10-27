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
```

## 覆盖范围

| 文件 | 覆盖 |
|---|---|
| `test_corpus.py` | 生成 / 导出 / 剪辑 / 配乐 / 设置 / 修订 / 指代 / 查询 / 问答 / 项目镜头 / 边界 |
| `test_step2.py` | 复合句拆多步、一次确认、两步连续写入 |
| `test_chain.py` | 依赖步骤延后 + 产物完成后自动续跑 |
| `test_audio.py` | 音频上传、附件进消息、对口型（lipsync）确认卡带参考音频 |
| `test_audio2.py` | 对口型按音频时长出片、多段参考音频、上传音频当 BGM |

## 约定

- 所有用例都在 `QA-` 前缀的临时项目里跑，结束时自动删除
- 不需要 GPU 的用例在确认卡处直接取消，不会提交真实任务
- 造历史产物用 `qa.add_artifacts()` 直接写库，不跑生成

# 交接：deepagents 迁移（2026-10-27 → 明日开工）

> 状态：spike 已验证，**生产代码未改动**。明天从这里开始换。

## 一句话结论

deepagents 值得换：工具选择 9/10、先查状态 10/10、确认门可桥接；瓶颈不在决策层，
在**事件桥接**（LangGraph 流 → 现有 SSE 契约）。

## 今天验证到什么

运行：`cd backend; python scripts/deepagent_spike.py`（全部工具干跑，不提交 ComfyUI）

| 维度 | 结果 |
|---|---|
| 工具选择（10 条真实语句） | 9/10 |
| 延迟 | 4.3 ~ 10.7s，均值 ≈6.6s |
| 先调 `describe_state` | 10/10 |
| 确认门 `interrupt_on` | `paused=true, interrupt_count=1` |
| 唯一失败 | 「生化危机」→ 反问，需在系统提示里要求「题材先扩写」 |

详细记录见 [spike-deepagents.md](spike-deepagents.md)。

### 两条必须记住的教训

1. **它的优势是"会先查"，不是"更会聊"**。`视频啊`、`把刚才那张图塞进第二镜当首帧`
   都能自己 `describe_state` + `list_shots` 后做对；我们现在是靠 `last_asset_id`、
   `last_topic` 一个个补字段。
2. **状态喂错，agent 只会更谨慎地停住**。spike 第一次跑 9/10 "失败"，原因是假上下文与
   工具返回不一致，它选择反问。所以「提示词变成文件路径」那类 bug 换框架也照样存在，
   需要单独保证状态干净。

## 明天的执行顺序

| 步骤 | 内容 | 估时 | 风险 |
|---|---|---|---|
| 1 | 15 个工具包成 LangChain tool（复用 spike 的写法） | 1 天 | 低 |
| 2 | `decide/planner` 换成 deepagents，**保留高频快通道** | 1 天 | 中 |
| 3 | `interrupt_on` → 现有确认卡（pending 字段对齐） | 1~1.5 天 | 中 |
| 4 | LangGraph 事件 → 现有 SSE（thinking / tool_call / step / message_delta） | 1 天 | **高** |
| 5 | 回归：现有测试 + 20 条未见说法对照 | 1 天 | 低 |

**建议先做第 1、2 步**，跑通「一句话 → 工具调用 → 确认卡」闭环，再动事件层；
事件层改动会同时影响前端渲染，最后做。

## 验收线（不能退）

- 现有 34 条语料 ≥ 31/31（`python tests/test_corpus.py`）
- 现有场景测试全绿：`test_agent_loop / test_vision / test_animate / test_topic / test_optimize / test_audio / test_audio2 / test_cancel / test_files_only / test_motion_prompt / test_step2`
- 新增 20 条**未写进规则**的说法，deepagents 版 ≥ 16/20
- 单句命令 P50 ≤ 1.5s（靠快通道）

## 现状盘点（换之前要知道的）

### 服务

```bash
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 6006
```

后端不常驻，需手动起；GUI `http://127.0.0.1:6006/?tab=agent`。

### 已实现的关键机制（迁移时别丢）

- **确认门**：`interrupt()` + SQLite checkpoint（`data/agent_state.db`）+ 前端确认卡，
  `POST /api/agent/runs/{id}/confirm`，取消后走本地回复（不再问模型）
- **产物编号**：`#1..#N`，带 `parent_ref` / `note` / `params`；`state.resolve()` 支持
  「刚才那个」「上一版」「第 N 镜」
- **多步计划**：`planner.py` → 一张确认卡确认全部步骤，逐条执行
- **视觉能力**：`llm.chat_vision()`；看图写运镜（i2v/r2v）、模糊修订翻译、改画幅构图建议
- **提示词优化**：`tools.optimize_prompt()`，视频卡默认过一遍 AI，确认卡标注「已优化」
- **话题记忆**：`last_topic` + 只答「视频啊」时按新题材生成
- **音频**：上传音频 → 对口型（按音频时长）→ 多段参考 → 上传音频当 BGM

### 已知脆弱点（迁移时顺手处理）

1. **状态字段散落**：`last_asset_id / last_kind / last_topic / last_prompt` 是逐个补的，
   建议在 deepagents 版里合并成一个 `SessionContext` 结构
2. **规则仍在前面挡**：`_fast_intent` 分支很多（约 200 行），迁移后应只保留高频快通道
3. **`_short_circuit` 容易抢**：多次 bug 都出在它抢先判定，需明确"只处理明确指代"
4. **前端事件契约**：`AgentPanel.tsx` 依赖 `t` 字段（`thinking/step/tool_call/message_delta/artifact/need_confirm`），
   桥接层必须保持这些名字，否则前端要改

## 当前分支状态

- 全部本地提交，**未推送**（用户要求自己 push）
- 最近提交：
  - `af1c9b3` spike：评估脚本 + 结论
  - `69d88a0` 视频提示词统一 AI 优化
  - `6ca4d41` 「让它动起来」走 i2v
  - `7de73be` 换话题按新题材生成
  - `1dea6ae` r2v 看图写运镜 + 视觉修订

## 明天第一件事

```bash
cd backend
python scripts/deepagent_spike.py     # 确认环境还在跑
python tests/test_corpus.py           # 确认基线 31/31
```

然后按表格第 1 步开始。

# Agent 助手 · M1 实施方案

> 依据：`docs/agent-design.md` + 2026-10-23 评审结论
>
> **已定决策**
>
> | 决策 | 结论 |
> |---|---|
> | Tab 名 | **导演助手**（放在「创作台」之前） |
> | 确认门 | **所有关键节点都确认**（文生图 / 视频 / 导出 / 写文件到项目） |
> | 会话绑定 | **一会话一项目**（`project_id` 必填，可先在项目页选定） |
> | M1 工具 | **图片生成 + 查素材**（外加只读的环境探测） |
> | 回放展示 | **默认折叠**，仿 DeepSeek Harness：一步一行，点开看思维/参数/原始返回 |
> | AI 剪辑迁移 | 排到 M2 之后 |

---

## 1. M1 范围（做什么 / 不做什么）

**做**

- 新建/切换会话，会话绑定项目
- 自然语言聊天（流式）
- 工具：`list_assets`、`make_image`、`job_status`、`env_check`（只读）
- **确认卡**：生成图片前必须确认（参数可改）
- 产物卡：图片 +「存为镜头 / 打开资产」
- 折叠式回放：每一步工具调用可展开
- 刷新恢复：会话历史、进行中的 run 都能续

**不做（M2+）**

- 视频生成、导出成片
- 多步编排（建项目 → 多镜 → 配乐）
- 指代消解（"再快一点"）中的复杂改稿
- deepagents / 子 agent

---

## 2. 后端结构

```
backend/app/agent/
├── __init__.py
├── graph.py        # LangGraph 编排：节点、边、interrupt
├── state.py        # AgentState TypedDict
├── tools.py        # 工具实现（直接调 store/presets，不走 HTTP）
├── prompts.py      # 系统提示 + 各节点提示
├── runtime.py      # 编译图、checkpointer、run 管理
├── events.py       # SSE 事件封装
└── store.py        # agent_* 表读写
```

依赖（新增到 `backend/requirements.txt`）：

```txt
langgraph>=1.0,<2
langchain-core>=1.0,<2
langchain-openai>=1.0,<2
aiosqlite
```

> 只装这三个，不装整个 `langchain`。模型走现成的 OpenAI 兼容配置（`ai.base_url` / `ai.api_key` / `ai.model`），多模态看图用 `ai.vision_model`。

---

## 3. 数据模型（migration `0010_agent_tables.py`）

```sql
CREATE TABLE agent_threads (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL DEFAULT '新对话',
  project_id  TEXT NOT NULL,
  model       TEXT NOT NULL DEFAULT '',
  created_at  REAL NOT NULL,
  updated_at  REAL NOT NULL,
  archived    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_agent_threads_project ON agent_threads(project_id, updated_at DESC);

CREATE TABLE agent_messages (
  id          TEXT PRIMARY KEY,
  thread_id   TEXT NOT NULL,
  run_id      TEXT,
  role        TEXT NOT NULL,          -- user | assistant | tool | system
  content     TEXT NOT NULL DEFAULT '',
  parts_json  TEXT NOT NULL DEFAULT '[]',   -- 多模态片段 / 卡片
  seq         INTEGER NOT NULL,
  created_at  REAL NOT NULL
);
CREATE INDEX idx_agent_messages_thread ON agent_messages(thread_id, seq);

CREATE TABLE agent_runs (
  id          TEXT PRIMARY KEY,
  thread_id   TEXT NOT NULL,
  status      TEXT NOT NULL,          -- running | waiting_confirm | done | failed | interrupted | canceled
  node        TEXT NOT NULL DEFAULT '',
  state_json  TEXT NOT NULL DEFAULT '{}',
  pending_json TEXT NOT NULL DEFAULT '{}',  -- 确认卡内容
  error       TEXT NOT NULL DEFAULT '',
  steps       INTEGER NOT NULL DEFAULT 0,
  started_at  REAL NOT NULL,
  finished_at REAL
);

CREATE TABLE agent_artifacts (
  id          TEXT PRIMARY KEY,
  run_id      TEXT NOT NULL,
  thread_id   TEXT NOT NULL,
  kind        TEXT NOT NULL,          -- image | video | asset | shot
  ref_id      TEXT NOT NULL DEFAULT '',
  url         TEXT NOT NULL DEFAULT '',
  meta_json   TEXT NOT NULL DEFAULT '{}',
  created_at  REAL NOT NULL
);
```

LangGraph checkpointer 用 `AsyncSqliteSaver`，落在同一个 `data/director.db`（独立表 `checkpoints*`），**不参与业务查询**。

---

## 4. 工具（M1 四个）

### 4.1 `env_check`

```python
def env_check() -> dict:
    # {"comfy_online": bool, "presets": [{"id","name","category","output_kind"}],
    #  "missing_models": [{"file","reason"}]}
```

只读，用来在系统提示里给模型"当前能干什么"。

### 4.2 `list_assets`

```python
list_assets(kind: str = "", q: str = "", purpose: str = "", limit: int = 10) -> list[dict]
# 返回 [{id, path, url, kind, purpose, width, height, size}]
```

直接调 `store.search_assets` + `_asset_purpose`。

### 4.3 `make_image`

```python
make_image(prompt: str, aspect: str = "9:16", seed: int = -1) -> dict
```

- 内部：`get_card("image.c16")` → 把 `prompt`/`size`/`seed` 映射成卡片 `inputs`
  （`{"49:text": prompt, "60:value": w, "61:value": h, "22:seed": seed}`，尺寸按 `aspect` 换算成 512 的倍数）
- 调 `store.create_job` + `runner.enqueue`（和 REST 层共用同一段逻辑，抽成 `_submit_job()`）
- **不在这里等结果**，返回 `{"job_id": ...}`

### 4.4 `job_status`

```python
job_status(job_id: str) -> dict
# {status, progress, message, outputs:[{kind,url}], error}
```

### 4.5 工具注册

用 LangChain 的 `@tool` 装饰，`args_schema` 用 Pydantic：

```python
@tool("make_image", description="生成一张图片。需要用户确认后才能调用。")
def make_image_tool(prompt: str, aspect: Literal["16:9","9:16","1:1","21:9"] = "9:16", seed: int = -1) -> str:
    ...
```

> 所有工具返回 **JSON 字符串**（LangChain tool 的 message content 是文本），并在返回体里带 `ok` 字段。

---

## 5. LangGraph 图（M1）

```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    project_id: str
    thread_id: str
    plan: dict            # 本轮意图 + 拟执行动作
    pending: dict         # 等待确认的动作
    artifacts: list[dict]
    steps: int
```

节点与边：

```
START → intake → decide ─┬─(chat)→ respond → END
                         ├─(lookup)→ run_tool → respond → END
                         └─(generate)→ prepare → interrupt(confirm)
                                                   │ resume(approved)
                                                   ▼
                                              dispatch → END（run 结束，等外部完成）
```

- `intake`：拼上下文（项目、能力卡摘要、最近素材），把用户消息写入 state
- `decide`：一次结构化输出（JSON），决定走哪条支路 + 抽参数
- `prepare`：把参数补全成卡片 `inputs`，生成确认卡内容（含预估耗时）
- `interrupt`：`interrupt({"summary":..., "params":..., "eta":...})`，run 状态置 `waiting_confirm`
- `resume`：用户点「执行」→ `Command(resume={"approved": True, "params": {...}})`
- `dispatch`：真正提交任务，写 `agent_artifacts`（占位，`kind=image`，`ref_id=job_id`）
- 任务完成后由 JobRunner 回调 `resume_completed(run_id, job)` 追加产物消息（**不重进图**，直接写消息 + 更新 artifact）

> M1 的关键取舍：**dispatch 后就结束 run**，任务结果以"新消息"形式追加，而不是让图等着。这样刷新、长任务、并发都不会互相拖累。

---

## 6. API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agent/threads?project_id=` | 会话列表（含最后一条消息摘要） |
| POST | `/api/agent/threads` | 新建会话 `{project_id, title?}` |
| PATCH | `/api/agent/threads/{id}` | 改名 / 归档 |
| DELETE | `/api/agent/threads/{id}` | 删会话（连带消息） |
| GET | `/api/agent/threads/{id}/messages?after_seq=` | 历史（分页/补拉） |
| POST | `/api/agent/threads/{id}/messages` | 发消息 `{text, attachments:[asset_id]}` → 返回 `run_id` |
| GET | `/api/agent/threads/{id}/stream?run_id=` | SSE 事件流 |
| POST | `/api/agent/runs/{id}/confirm` | `{action:"run"|"cancel", params?}` |
| POST | `/api/agent/runs/{id}/cancel` | 中断当前 run |

### SSE 事件（M1 用到 6 种）

```jsonl
{"t":"run_start","run_id":"run_x","seq":1}
{"t":"step","id":"s1","node":"decide","title":"理解需求","detail":{"intent":"generate"},"status":"done"}
{"t":"message","delta":"我来生成一张"}
{"t":"tool_call","id":"c1","name":"make_image","args":{"prompt":"...","aspect":"9:16"}}
{"t":"tool_result","id":"c1","ok":true,"data":{"job_id":"job_x"}}
{"t":"need_confirm","id":"cf1","summary":"生成图片","params":{...},"eta":"约 40 秒"}
{"t":"artifact","kind":"image","ref_id":"job_x","url":"..."}
{"t":"run_end","status":"waiting_confirm"|"done"|"failed"}
```

`step` 事件就是**回放数据源**：前端默认折叠成一行 `▸ 理解需求`，点开看 `detail`。

---

## 7. 前端

### 7.1 文件

```
web/src/components/agent/
├── AgentPanel.tsx        # 页面壳：左对话 + 右画布
├── ThreadList.tsx        # 会话切换（顶部下拉，不做侧栏）
├── MessageList.tsx
├── MessageBubble.tsx     # 文本 / 图片 / 产物卡
├── ToolCard.tsx          # 折叠式：标题 + 状态 + 展开详情
├── StepTrace.tsx         # 折叠回放（仿 harness）
├── ConfirmCard.tsx       # 参数可编辑 + [执行][取消]
├── Composer.tsx          # 输入框 + 附件 + 能力提示
└── AgentCanvas.tsx       # 右栏：当前任务进度 + 最近产物
```

`App.tsx` 加 tab：

```ts
type Tab = 'agent' | 'studio' | 'projects' | ...
// 导航顺序：导演助手 创作台 项目 剪辑 资产 成片 任务 服务管家
```

### 7.2 折叠回放样式（对齐 DeepSeek Harness）

```
▸ 理解需求                    0.8s
▸ 查素材「黑猫」               12ms
▸ 生成图片 · 9:16              需要确认
  ┌ 展开后 ─────────────────────────────┐
  │ 参数：prompt / aspect / seed          │
  │ 卡片：image.c16                       │
  │ 原始返回：{"ok":true,...}             │
  └──────────────────────────────────────┘
```

- 默认全部折叠，只显示标题 + 状态点 + 耗时
- 折叠时不占高度，连续步骤视觉上是一条细线
- 错误状态自动展开

### 7.3 状态管理

- `useAgentThread(threadId)`：消息、run、SSE 连接
- SSE 断线：用 `?after=<seq>` 重连补事件
- 切 tab 不卸载（`display:none` 保活），避免重连

---

## 8. 系统提示（M1 版，节选）

```
你是「导演助手」，替用户在 优墨导演台里完成出图任务。

环境：
- ComfyUI：{online}
- 可用的图片能力卡：{cards}
- 缺失模型：{missing}

项目：{project_name}（{shot_count} 个镜头，风格：{style}）

规则：
1. 参数不全时最多追问 1 个问题，其余用默认值，并在确认卡里列出来。
2. 生成图片前必须调用 make_image，且必须等用户确认——你不需要自己问"要不要生成"，
   确认卡就是询问。
3. 不要编造 job_id / asset_id，只能引用工具返回的。
4. 回复用短句，先结论后细节；产物用卡片展示，不要在正文里贴 URL。
5. 用户说"看看素材"时用 list_assets，不要凭空描述文件。
```

结构化输出（`decide` 节点用 JSON mode）：

```json
{"intent":"chat|lookup|generate","reason":"...","tool":"list_assets|make_image|null",
 "args":{"prompt":"...","aspect":"9:16","q":"黑猫","kind":"image"},
 "reply_hint":"给用户的一句话"}
```

---

## 9. 验收标准

| # | 场景 | 期望 |
|---|---|---|
| 1 | 打开导演助手 | 自动建会话或选中上次会话，绑定当前项目 |
| 2 | "帮我看看素材库里有什么猫的图" | 调 `list_assets`，返回 3~5 条素材卡，可点开 |
| 3 | "生成一只黑猫在雪地里走，竖屏" | 弹确认卡（9:16，约 40 秒），点执行后提交任务 |
| 4 | 任务进行中刷新页面 | 会话历史还在，右栏仍在轮询进度，完成后出现产物卡 |
| 5 | 点「存为镜头」 | 跳到项目，镜头列表多一条 |
| 6 | 展开回放 | 能看到每个节点的参数与原始返回 |
| 7 | ComfyUI 离线时发"生成一张图" | 直接回复离线提示，不弹出无意义的确认卡 |
| 8 | 连续 10 轮对话 | 上下文不爆（摘要生效），响应仍 < 3s 首字 |

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| 模型不稳定，`decide` 输出非法 JSON | 用 `with_structured_output` + 失败重试 2 次，仍失败则降级为纯聊天 |
| 用户反复改参数导致确认卡堆积 | 一个 run 同时只有一个 pending 确认；新消息进来先取消旧 pending |
| LangGraph 版本 API 漂移 | 锁 `<2`，checkpointer 与图定义集中在 `runtime.py` |
| SSE 与浏览器多标签竞争 | 每线程只允许一个活跃 SSE，新连接踢掉旧连接 |
| 图片卡片参数映射硬编码 | 把 `card.fields` 的 bind 解析抽成 `build_image_inputs(card, params)`，单测覆盖 |

---

## 11. 实施顺序（4 步）

1. **数据层**：migration + `agent/store.py` + 单测
2. **工具层**：`env_check` / `list_assets` / `make_image` / `job_status` + 单测（不依赖 LLM）
3. **图与接口**：`graph.py` + SSE + 三个确认端点（用假 LLM 跑通全链路）
4. **前端**：AgentPanel + 折叠回放 + 确认卡 + 产物卡

每步可独立验收，前两步不需要 LLM 也能测。

# Phase B 记录（2026-10-28）

> 承接 [migration-deepagents-day2.md](migration-deepagents-day2.md)。今天做 Phase B：
> 规则降级、事件桥接、依赖补齐、多步上限提升。

## 1. 依赖（requirements.txt）

```text
deepagents>=0.7,<0.8
```

同时会带入 `langchain`、`langsmith`、`wcmatch` 等（deepagents 0.7 的依赖）。安装后
`langchain-core` 1.7 与 `langchain-community` 0.3 存在版本告警，但本项目不依赖
community 包，运行无影响。

## 2. 规则降级：只留高频确定性命令

`_fast_intent` 现在只处理：

| 保留 | 理由 |
|---|---|
| 出图 / 出视频（含运镜、参考图、首帧、第 N 镜、对口型） | 最高频，0.5s 直达 |
| 导出成片 | 高频且无歧义 |
| 查询（素材 / 镜头 / 体检） | 直接读库，比模型快且准 |
| 问答（能力卡 / 工作流 / 区别） | 固定文案，稳定 |
| 附件确认（只发文件不说话） | 确定性交互 |
| 题材选择（「视频啊」） | 依赖 last_topic，规则最快 |
| **改片（revise）** | 需要精确解析「第几张 / 刚才那个 / 上一版」，规则更稳 |

交给 deepagents 引擎：

- 配乐（set_bgm）
- AI 剪辑（polish_film）
- 片头片尾 / 成片设置（set_film_options）
- 新建项目（create_project）
- 加镜头 / 存镜头（add_shots / save_shot）
- 其余长尾说法

> 说明：改片最终**保留在规则层**。试过完全交给引擎，语料从 31/31 掉到 26/31，
> 原因是引擎不擅长「第 2 张」这种下标解析。规则负责定位，引擎负责其它判断。

## 3. 事件桥接：引擎「查了什么」变成可见步骤

引擎的只读工具（describe_state / list_shots / find_assets / card_info）和动作工具都会记一条
log，`node_decide` 把它转成前端的 `step` 事件：

```
读取上下文 → 理解需求 → 查看会话产物 → 读取镜头列表 → 需要确认
```

SSE 实测：`['run_start','step','step','step','tool_call','tool_result','need_confirm']`。

## 4. 多步计划

- 上限从 3 提到 **5**（`da_engine.MAX_STEPS`、`planner.MAX_STEPS`）
- 新增 `save_shot` 工具，`planner.TOOLS` 同步
- 复合句式（`looks_compound`：「A，然后 B」）在 `_fast_intent` 入口直接放行给规划器，
  不再被单意图规则截胡；`test_step2` 5/5 通过（配乐+片头、字幕+导出、出图+视频、连续执行）

## 5. 结论（不粉饰）

| 项 | 结果 |
|---|---|
| 语料 | **31/31**（规则降级后仍全绿） |
| 多步计划 | **5/5**（复合句已跳过规则，交给 planner/引擎拆步） |
| 规则代码量 | 少了 7 个分支（配乐/剪辑/片头/新建/加镜头/存镜头…） |
| 长尾覆盖 | 比 Phase A 略好：这类说法现在真的进引擎了 |
| 多步 | 上限提到 5，但复合句式仍被规则截胡，未达目标 |
| 确认门 | 继续用现有确认卡（可编辑参数），**没有换 interrupt_on**——见下 |

### 为什么没换 interrupt_on

试下来，现有确认卡比 deepagents 原生中断**更适合产品**：用户能在卡上直接改提示词、
画幅、时长、清晰度。`interrupt_on` 只能「暂停/放行」，改参数还得再加一层。

代价是多步计划的「执行到第 N 步再问」暂时做不到——现在是一次性确认全部步骤。
如果后面确实需要，再在 dispatch_multi 上加断点，不必动 interrupt_on。

## 5.1 回归结果（2026-10-28）

12 个测试文件逐个跑：**全部通过**。整套连续跑时出现过 3 个瞬时失败
（test_cancel / test_files_only / test_motion_prompt），单独重跑全部通过——
判断为连续调用下上游模型延迟/限流导致，不是逻辑问题。已记录，后续给测试加
重试或错峰。

## 6. 明天可做

1. 复合句式（「先…再…」「三镜短片」）跳过规则，交给引擎做多步
2. 多步确认卡支持「逐条执行 / 全部执行」
3. 引擎结果缓存（同一句话重复说，省一次 5s）
4. 量化：把「未写进规则的 20 条说法」固化成测试，防止以后退化


## 7. 前端：气泡支持 markdown（2026-10-28 下午）

- 新增 `web/src/components/agent/MarkdownText.tsx`（react-markdown + remark-gfm）
- 助手消息与流式输出都走 markdown 渲染；表格、列表、代码块、引用、链接（新窗口打开）
- 样式补在 `styles.css`：表格横向滚动、`th` 背景、代码块底色
- 构建注意：esbuild 的临时目录默认在 `%TEMP%`，本机偶发 `Access is denied`，
  构建前把 `TEMP/TMP` 指到 `web/.tmp` 即可。

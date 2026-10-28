# deepagents 迁移进度（Day 2 / Phase A）

> 承接 [handoff-deepagents.md](handoff-deepagents.md)。今天完成 Phase A：把决策层换成
> deepagents，**确认卡与 SSE 全部复用**，并加了可回滚开关。

## 今天做完的

| 内容 | 文件 |
|---|---|
| deepagents 决策引擎（只提议、不执行） | `backend/app/agent/da_engine.py` |
| 4 个只读工具 + 9 个动作工具（闭包收集提案） | 同上 |
| 引擎开关 `agent.engine`（rules / deepagents） | `backend/app/config.py`、`runtime.py` |
| 运行时切换接口 | `GET/PUT /api/settings/agent` |
| 决策层接入（规则接不住时才用引擎） | `backend/app/agent/graph.py` |

## 关键设计：只提议，不执行

动作工具**不落库、不提交 ComfyUI**，只把「打算做什么」记进一个列表，返回给 graph，
再走现有 `prepare → confirm → dispatch`。好处：

- 确认卡、SSE 事件、多步计划、产物编号全部不用改
- 出图出片依然要用户点「执行」
- 出问题只影响「决策」，不影响「执行」

## 实测

| 指标 | 结果 |
|---|---|
| 未见说法对照（10 条，隔离） | rules 7/7，deepagents 7/7（持平） |
| 现有语料 | 31/31 |
| 关键场景（做视频/让它动起来/塞进第二镜/体检/查素材） | 全部走通 |
| 单条延迟 | 4~10s（规则命中时仍 0.5s） |

**诚实结论：Phase A 是「持平」，不是「变强」。** 因为规则仍在前面挡着，引擎只处理
规则接不住的话；而规则已经覆盖了这些例子。变强要等 Phase B —— 把更多判断交给引擎，
只保留极少数高频确定性命令走规则。

## 顺手修掉的两个规则 bug（两个引擎都受益）

1. **运镜词被当出图**：「把我刚传的那张当底图，做个环绕」→ 原来判成出图（`图` 字命中），
   现在「环绕/推近/拉远/运镜/跟拍」+ 有图 → 图生视频
2. **题材选择要先于素材检查**：「视频啊」在没有任何素材的会话里也能按题材出片
3. 主观评价词扩充：太艳 / 颜色 / 色调 / 太亮 / 发灰 → 走视觉修订

## 怎么切回去

```bash
curl -X PUT http://127.0.0.1:6006/api/settings/agent -H "Content-Type: application/json" -d "{\"engine\":\"rules\"}"
```

默认已改为 `deepagents`（`config.py` + 数据库覆盖都支持）。

## 明天（Phase B）

1. **规则降级**：只保留「画一张 / 做一个视频 / 导出 / 取消 / 加镜头 / 建项目」这类高频确定性
   命令；主观评价、指代、多步、组合意图全部交给引擎
2. **确认门换成 `interrupt_on`**：现在还是复用旧确认卡；换成 deepagents 原生中断后，
   可以支持「执行到第 2 步再问」这种细粒度
3. **事件桥接**：LangGraph 事件 → 现有 SSE 契约（thinking / tool_call / step / message_delta）
4. **多步计划**：目前引擎一次最多 3 步，但未验证「三镜短片」这类长计划

## 风险记录

- `da_engine.decide()` 每次新建 agent + MemorySaver，编译开销未测（延迟里已含）
- 同一进程内 ChatOpenAI 的 httpx client 绑定事件循环，脚本里连续 `asyncio.run` 会报
  `Event loop is closed`；服务内单循环无此问题
- 动作工具用闭包收集，避免 contextvar 在线程池里丢失（已踩过）

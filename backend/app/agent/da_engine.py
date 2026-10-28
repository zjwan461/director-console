"""deepagents 决策引擎（Phase A）。

设计原则：
1. **只做决策，不执行**。动作工具不落库、不提交 ComfyUI，只把「打算做什么」记进
   PROPOSALS，交回现有 prepare → confirm → dispatch 流程。这样确认卡、SSE 事件、
   多步计划全部复用，迁移风险最小。
2. 只读工具是真查（产物、镜头、素材、能力卡），让模型能「先看再决定」。
3. 由 `agent.engine` 配置切换：rules（现有）/ deepagents。

后续 Phase B 再把确认门换成 deepagents 原生 interrupt_on。
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

from . import planner, state as agent_state, store as agent_store, tools
from .. import store

MAX_STEPS = 5

SYSTEM = """你是「导演台」的执行大脑。用户用自然语言说要做什么，你负责决定调用哪些工具。

## 你能做什么
- 出图：make_image（剧照 / 角色图 / 场景图）
- 出视频：make_video，mode 三选一
  · t2v：只有文字描述，没有参考图
  · i2v：用会话里已有的一张图当首帧
  · r2v：拿参考图生成（保留人物/风格）
- 改上一版：revise（提高亮度、换画幅、改时长、加元素…）
- 成片相关：export_film 导出、polish_film 字幕旁白、set_bgm 配乐、set_film_options 片头片尾
- 项目管理：create_project 新建、add_shots 加镜头

## 铁律
1. **先查后做**：用户说「这张图 / 刚才那个 / 第几镜 / 上一版」时，必须先调
   describe_state 或 list_shots 确认到底指什么，不要猜。
2. **一次最多 3 步**，能一步完成不要拆。后一步依赖前一步产物时，在 args 里写
   depends_on=<前一步序号>，并且视频用 mode=i2v。
3. **提示词要写成可拍的画面描述**：主体与动作 + 环境 + 光线 + 运镜，40~70 字。
   用户只给题材（如「生化危机」）时，扩写成具体画面再出片。
4. **只说不做**：调用动作工具只是"排入确认队列"，不会真的出图出片；用户会看到确认卡。
5. 用户只是聊天/提问时，不要调动作工具，直接在回复里说清楚。
6. **改时长/改画幅/提亮/换颜色/加元素** 一律用 revise（例如「拉长两秒」「颜色太艳」「换成红衣」），
   不要说"没有视频所以改不了"——revise 会作用在最近那一版产物上。
7. **「做个环绕 / 推近 / 拉远 / 转一圈」这类是运镜**，属于 make_video（有图就 i2v），不是出图。
8. 不要编造用户没说的信息；拿不准就问一句。

## 当前上下文
{state}
"""


def _state_text(thread_id: str, project_id: str, attachments: list[dict]) -> str:
    st = agent_state.thread_state(thread_id)
    project = store.get_project(project_id) if project_id else None
    name = (project or {}).get("name") or "未命名"
    lines = [f"- 当前项目：《{name}》（{project_id or '未绑定'}）",
             f"- 会话产物：{st['count']} 个"]
    for item in st["artifacts"][-6:]:
        note = item.get("note") or (item.get("prompt") or "")[:24]
        params = item.get("params") or {}
        bits = []
        for key in ("mode", "aspect", "duration", "megapixels"):
            if params.get(key) not in (None, "", 0):
                bits.append(f"{key}={params[key]}")
        extra = f"［{', '.join(bits)}］" if bits else ""
        lines.append(f"    #{item['ref']} {item['kind']}：{note}{extra}")
    shots = agent_state._shot_refs(project_id)
    if shots:
        lines.append(f"- 项目镜头：{len(shots)} 个")
        for shot in shots[:8]:
            cover = "有画面" if shot.get("cover") else "还没画面"
            lines.append(f"    {shot['ref']} {shot['title']}（{cover}）")
    if attachments:
        lines.append("- 本条消息附件：")
        for att in attachments:
            name = str(att.get("path") or "").rsplit("/", 1)[-1]
            lines.append(f"    {att.get('kind')} asset_id={att.get('id')} {name}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 只读工具（真查）
# --------------------------------------------------------------------------- #
def _build_read_tools(log: list[dict]):
    @tool
    def describe_state(thread_id: str) -> str:
        """查看当前会话有哪些产物（#编号、类型、备注、参数），以及项目镜头。"""
        log.append({"tool": "describe_state", "kind": "read", "args": {}})
        st = agent_state.thread_state(thread_id)
        return json.dumps({
            "artifacts": [{"ref": a["ref"], "kind": a["kind"],
                           "note": a["note"] or a["prompt"][:30], "params": a["params"]}
                          for a in st["artifacts"][-8:]],
            "count": st["count"], "last_ref": st["last_ref"],
        }, ensure_ascii=False)

    @tool
    def list_shots(project_id: str) -> str:
        """列出项目里的镜头：序号、标题、有没有画面。"""
        log.append({"tool": "list_shots", "kind": "read", "args": {}})
        shots = agent_state._shot_refs(project_id)
        return json.dumps([{"ref": s["ref"], "title": s["title"],
                            "has_cover": bool(s.get("cover"))} for s in shots],
                          ensure_ascii=False)

    @tool
    def find_assets(kind: str = "", q: str = "") -> str:
        """按类型（image / video / audio）和关键词查素材库。"""
        log.append({"tool": "find_assets", "kind": "read", "args": {"kind": kind, "q": q}})
        data = json.loads(tools.list_assets(kind, q, "", 6))
        return json.dumps([{"id": i["id"], "kind": i.get("kind"), "path": i.get("path")}
                           for i in (data.get("items") or [])[:6]], ensure_ascii=False)

    @tool
    def card_info(card_id: str) -> str:
        """查某张能力卡的参数（例如 h3.i2v、image.c16）。"""
        log.append({"tool": "card_info", "kind": "read", "args": {"card_id": card_id}})
        card = tools.get_card(card_id)
        if not card:
            return json.dumps({"error": "没有这张能力卡"}, ensure_ascii=False)
        public = tools.public_card(card)
        return json.dumps({
            "id": public.get("id"), "name": public.get("name"),
            "fields": [{"key": f.get("key"), "type": f.get("type"),
                        "required": f.get("required")} for f in (public.get("fields") or [])],
        }, ensure_ascii=False)

    return [describe_state, list_shots, find_assets, card_info]


# --------------------------------------------------------------------------- #
# 动作工具（只提议，不执行）
# 用闭包收集，避免 deepagents 在别的线程里执行工具时 contextvar 传不进去
# --------------------------------------------------------------------------- #
def _build_action_tools(bucket: list[dict], log: list[dict]):
    def append(tool_name: str, args: dict, why: str) -> str:
        if len(bucket) >= MAX_STEPS:
            return json.dumps({"ok": False, "reason": "一次最多 3 步，已经够了"},
                              ensure_ascii=False)
        bucket.append({"tool": tool_name, "args": args, "why": why})
        log.append({"tool": tool_name, "kind": "action", "args": args})
        return json.dumps({"ok": True, "proposed": tool_name, "step": len(bucket),
                           "note": "已排入确认队列，等用户确认后才会执行"}, ensure_ascii=False)

    @tool
    def make_image(prompt: str, aspect: str = "9:16", megapixels: float = 1.0,
                   why: str = "") -> str:
        """出图。prompt 必须是可拍的画面描述；aspect 如 9:16、16:9、1:1。"""
        return append("make_image", {"prompt": prompt, "aspect": aspect,
                                     "megapixels": megapixels}, why)

    @tool
    def make_video(prompt: str, mode: str = "t2v", duration: float = 5,
                   aspect: str = "16:9", depends_on: int = 0, why: str = "") -> str:
        """出视频。mode: t2v 文生 / i2v 用现有图当首帧 / r2v 参考图；依赖前一步时 depends_on 填序号。"""
        args = {"prompt": prompt, "mode": mode, "duration": duration, "aspect": aspect}
        if depends_on:
            args["depends_on"] = depends_on
        return append("make_video", args, why)

    @tool
    def revise(raw: str, why: str = "") -> str:
        """在上一版基础上改（提亮、换画幅、改时长、加/减元素）。raw 写清楚要改什么。"""
        return append("revise", {"raw": raw}, why)

    @tool
    def export_film(quality: str = "high", why: str = "") -> str:
        """导出成片。"""
        return append("export_film", {"quality": quality}, why)

    @tool
    def polish_film(kinds: str = "both", tts: bool = True, why: str = "") -> str:
        """AI 剪辑：补字幕、写旁白、配音。kinds: subtitle / narration / both。"""
        return append("polish_film", {"kinds": kinds, "tts": tts}, why)

    @tool
    def set_bgm(mode: str = "auto", query: str = "", why: str = "") -> str:
        """配背景音乐。mode: auto 按风格自动选 / asset 指定素材 / off。"""
        return append("set_bgm", {"mode": mode, "query": query}, why)

    @tool
    def set_film_options(raw: str, why: str = "") -> str:
        """成片设置：片头、片尾、画幅、字幕开关等。raw 写清楚。"""
        return append("set_film_options", {"raw": raw}, why)

    @tool
    def create_project(name: str, why: str = "") -> str:
        """新建项目。"""
        return append("create_project", {"name": name}, why)

    @tool
    def save_shot(why: str = "") -> str:
        """把最近那一版产物存成项目镜头。"""
        return append("save_shot", {}, why)

    @tool
    def add_shots(raw: str, why: str = "") -> str:
        """新增镜头。raw 写清楚几个镜头、每个镜头是什么。"""
        return append("add_shots", {"raw": raw}, why)

    return [make_image, make_video, revise, export_film, polish_film,
            set_bgm, set_film_options, create_project, add_shots, save_shot]




def _model():
    from langchain_openai import ChatOpenAI
    from ..config import settings

    return ChatOpenAI(
        model=str(settings.get("ai.model") or ""),
        base_url=str(settings.get("ai.base_url") or ""),
        api_key=str(settings.get("ai.api_key") or ""),
        temperature=0,
        timeout=180,
        max_retries=1,
    )


async def decide(text: str, thread_id: str, project_id: str,
                 attachments: list[dict] | None = None) -> dict:
    """返回 {"steps": [...], "reply": str, "source": "deepagents"|"error"}。"""
    from deepagents import create_deep_agent
    from langgraph.checkpoint.memory import MemorySaver
    from .. import llm

    attachments = attachments or []
    if not llm.ready():
        return {"steps": [], "reply": "还没配置大模型（设置 → AI）。", "source": "error"}

    bucket: list[dict] = []
    log: list[dict] = []
    read_tools = _build_read_tools(log)
    action_tools = _build_action_tools(bucket, log)
    try:
        agent = create_deep_agent(
            model=_model(),
            tools=read_tools + action_tools,
            system_prompt=SYSTEM.format(
                state=_state_text(thread_id, project_id, attachments)),
            checkpointer=MemorySaver(),
        )
        config = {"configurable": {"thread_id": f"decide_{thread_id}_{abs(hash(text)) % 100000}"}}
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": text}]}, config)

        steps = planner.normalize(list(bucket))
        reply = ""
        for msg in reversed(result.get("messages") or []):
            if getattr(msg, "type", "") == "ai" and str(getattr(msg, "content", "")).strip():
                reply = str(msg.content).strip()
                break
        return {"steps": steps, "reply": reply[:400], "source": "deepagents",
                "calls": list(log)}
    except Exception as exc:
        return {"steps": [], "reply": f"决策失败：{type(exc).__name__}: {exc}"[:300],
                "source": "error", "calls": list(log)}

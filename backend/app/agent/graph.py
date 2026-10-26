"""LangGraph 编排：intake → decide → (chat | lookup | prepare) → 确认 → dispatch。

M1 的取舍：dispatch 之后立即结束 run，任务结果由 watch_job 作为「新消息」追加，
不把图挂在等待上——刷新页面、长任务、并发都不会互相拖累。
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.config import get_config
from langgraph.types import interrupt

from .. import store
from ..config import settings
from . import store as agent_store
from . import prompts, tools


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    thread_id: str
    project_id: str
    run_id: str
    text: str
    intent: str
    reply: str
    args: dict
    plan: dict
    decision: str
    attachments: list
    streamed: bool
    error: str


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
def _llm():
    from langchain_openai import ChatOpenAI

    base = str(settings.get("ai.base_url", "") or "").rstrip("/")
    key = str(settings.get("ai.api_key", "") or "")
    model = str(settings.get("ai.model", "") or "")
    if not base or not key or not model:
        return None
    return ChatOpenAI(
        model=model,
        base_url=base,
        api_key=key,
        temperature=0.3,
        timeout=60,
        max_retries=1,
    )


def _config() -> dict:
    try:
        return get_config() or {}
    except Exception:
        return {}


def _emit(event: dict, config: dict | None = None) -> None:
    cfg = config if config is not None else _config()
    sink = (cfg.get("configurable") or {}).get("emit")
    if callable(sink):
        sink(event)


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}
        return {}


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
async def node_intake(state: AgentState) -> dict:
    _emit({"t": "step", "id": "intake", "node": "intake",
                   "title": "读取上下文", "status": "done", "detail": {}})
    return {"error": ""}


AFFIRM_RE = re.compile(
    r"(可以|好的|好吧|好嘞|好|行|嗯|对|是的|继续|开始|就用|用这张|用那张|用这个|来吧|走起|ok|okay|yes)",
    re.IGNORECASE)
NEGATIVE_RE = re.compile(r"(不好|不要|别用|不用|取消|算了|重新|换一张|换个|先不)")

VIDEO_WORDS = ("视频", "动起来", "动一下", "运镜", "动画", "几秒", "秒的片子", "出片")


def _is_affirmative(text: str) -> bool:
    text = (text or "").strip().strip("。.!！~ ")
    if not text or len(text) > 16:  # 太长的多半是新需求，不当作"同意"
        return False
    if NEGATIVE_RE.search(text):
        return False
    return bool(AFFIRM_RE.search(text.replace(" ", "")))


def _short_circuit(state: AgentState) -> dict | None:
    """上一轮刚出了图，这一轮说「可以/就用这张」，直接推进成图生视频。

    这是纯规则判断，不依赖模型——否则用户得写一长串提示词才能让流程继续。
    """
    thread_id = state.get("thread_id", "")
    text = state.get("text", "") or ""
    ctx = agent_store.get_context(thread_id)
    asset_id = str(ctx.get("last_asset_id") or "")
    if not asset_id:
        return None

    video_intent = any(word in text for word in VIDEO_WORDS)
    if not (_is_affirmative(text) or video_intent):
        return None
    # 用户明确要图片/重新画时，不要抢
    if any(word in text for word in ("重新画", "再画", "生成图片", "换一张图")):
        return None

    prompt = str(ctx.get("last_prompt") or "").strip() or "让画面动起来"
    return {
        "intent": "generate_video",
        "args": {
            "prompt": prompt,
            "mode": "i2v",
            "image_asset_id": asset_id,
            "aspect": "9:16",
            "duration": 5,
        },
        "reply": "好，拿这张图当首帧，我来生成一条动态镜头。",
    }


async def node_decide(state: AgentState) -> dict:
    shortcut = _short_circuit(state)
    if shortcut:
        _emit({"t": "step", "id": "decide", "node": "decide", "title": "接着上一步",
               "status": "done", "detail": {"intent": shortcut["intent"],
                                             "reason": "肯定回复 + 最近有产物"}})
        return {**shortcut, "decision": ""}

    env = json.loads(tools.env_check())
    env.pop("presets", None)  # 提示词里只留必要信息
    project = store.get_project(state.get("project_id", "")) or {}
    shots = store.list_shots(state.get("project_id", "")) if project else []
    project_ctx = {**project, "shot_count": len(shots)} if project else None

    ctx = agent_store.get_context(state.get("thread_id", ""))
    if ctx:
        project_ctx = dict(project_ctx or {})
        project_ctx["最近一次产物"] = {
            "类型": ctx.get("last_kind", ""),
            "任务": ctx.get("last_job_id", ""),
            "画面描述": (ctx.get("last_prompt") or "")[:120],
            "可以当首帧的素材": ctx.get("last_asset_id", ""),
        }

    attachments = state.get("attachments") or []
    if attachments:
        lines = [f"- asset_id={a['id']}，文件 {a['path'].rsplit('/', 1)[-1]}"
                 for a in attachments if a.get("kind") == "image"]
        if lines:
            project_ctx = dict(project_ctx or {})
            project_ctx["用户随消息上传的图片"] = lines

    llm = _llm()
    if llm is None:
        return {"intent": "chat",
                "reply": "还没配置大模型（设置 → AI），先配好我才能帮你出图。",
                "args": {}}

    history = [m for m in state.get("messages", []) if isinstance(m, (HumanMessage, AIMessage))]
    msgs = [SystemMessage(content=prompts.system_prompt(env, project_ctx)), *history[-12:]]
    try:
        resp = await llm.ainvoke(msgs)
        data = _parse_json(getattr(resp, "content", "") or "")
    except Exception as exc:  # LLM 挂了也不能让会话崩
        return {"intent": "chat", "reply": f"我这边调用模型失败了：{exc}", "args": {}}

    intent = str(data.get("intent") or "chat").strip()
    if intent not in {"chat", "lookup", "generate", "generate_video", "export", "save_shot"}:
        intent = "chat"
    reply = str(data.get("reply") or "").strip()
    args = data.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    _emit({"t": "step", "id": "decide", "node": "decide", "title": "理解需求",
                   "status": "done", "detail": {"intent": intent, "args": args}})
    return {"intent": intent, "reply": reply, "args": args}


async def node_chat(state: AgentState) -> dict:
    """闲聊/解释走这里：真流式输出，前端能一个字一个字看到。"""
    llm = _llm()
    fallback = state.get("reply") or ""
    if llm is None:
        return {"reply": fallback or "还没配置大模型（设置 → AI）。"}

    env = json.loads(tools.env_check())
    env.pop("presets", None)
    project = store.get_project(state.get("project_id", "")) or {}
    shots = store.list_shots(state.get("project_id", "")) if project else []
    project_ctx = {**project, "shot_count": len(shots)} if project else None

    history = [m for m in state.get("messages", []) if isinstance(m, (HumanMessage, AIMessage))]
    msgs = [
        SystemMessage(content=prompts.system_prompt(env, project_ctx)),
        *history[-12:],
        SystemMessage(content="现在用一段自然口语回答用户，不要输出 JSON，不要罗列工具名。"),
    ]

    text = ""
    try:
        async for chunk in llm.astream(msgs):
            delta = getattr(chunk, "content", "") or ""
            if not delta:
                continue
            text += delta
            _emit({"t": "message_delta", "text": delta})
    except Exception as exc:
        if not text:
            return {"reply": fallback or f"我这边调用模型失败了：{exc}"}

    return {"reply": text.strip() or fallback or "我在。", "streamed": True}


async def node_lookup(state: AgentState) -> dict:
    args = state.get("args") or {}
    params = {"q": str(args.get("q") or ""), "kind": str(args.get("kind") or "")}
    _emit({"t": "tool_call", "id": "assets", "name": "list_assets", "args": params})
    data = json.loads(tools.list_assets(**params, limit=6))

    # 素材是按文件名检索的，中文描述经常搜不到；空了就退回「最近的同类素材」
    fallback = False
    if data.get("ok") and not data.get("items"):
        fallback = True
        data = json.loads(tools.list_assets(kind=params["kind"], limit=6))

    items = (data.get("items") or [])[:6]
    _emit({"t": "tool_result", "id": "assets", "ok": bool(data.get("ok")),
           "data": {"total": data.get("total", 0), "items": items, "fallback": fallback}})

    if not data.get("ok"):
        reply = "查素材失败了：" + str(data.get("hint") or data.get("error"))
    elif not items:
        reply = "素材库里还没有符合条件的素材。"
    else:
        names = "、".join(str(item.get("path", "")).rsplit("/", 1)[-1] for item in items[:4])
        head = "没搜到更贴切的，" if fallback else ""
        reply = f"{head}找到 {data.get('total', len(items))} 个，比如：{names}。"

    return {"reply": reply, "args": {**args, "assets": items}}


async def node_prepare(state: AgentState) -> dict:
    # 生成前先确认 ComfyUI 活着，否则不要给用户弹无意义的确认卡
    try:
        import asyncio as _asyncio

        from ..comfy import make_client

        await _asyncio.wait_for(make_client().health(), timeout=4)
    except Exception as exc:
        hint = str(exc)[:80] or type(exc).__name__
        return {"intent": "chat",
                "reply": f"ComfyUI 现在连不上（{hint}），先去看服务管家把它启起来，再让我干活。"}

    args = state.get("args") or {}
    intent = state.get("intent") or "generate"
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"intent": "chat", "reply": "能再说清楚一点画面内容吗？我好照着画。"}

    if intent == "generate_video":
        mode = str(args.get("mode") or "t2v").strip()
        if mode not in tools.VIDEO_CARDS:
            mode = "t2v"
        asset_id = str(args.get("image_asset_id") or "").strip()

        # i2v / r2v 需要图：先从素材库按关键词找一张
        if mode in {"i2v", "r2v"} and not asset_id:
            query = str(args.get("image_query") or "").strip() or prompt[:12]
            found = json.loads(tools.list_assets(kind="image", q=query, limit=3))
            items = found.get("items") or []
            if not items:
                found = json.loads(tools.list_assets(kind="image", limit=3))
                items = found.get("items") or []
            if not items:
                return {"intent": "chat",
                        "reply": "素材库里还没有图片，先把一张图放进资产，再让我做图生视频。"}
            asset_id = str(items[0]["id"])
            _emit({"t": "step", "id": "pick_image", "node": "prepare",
                   "title": "挑选参考图", "status": "done",
                   "detail": {"asset": items[0].get("path"), "matched": bool(found.get("items"))}})

        preview = tools.video_inputs_preview(
            prompt, mode, str(args.get("aspect") or ""),
            float(args["duration"]) if args.get("duration") else None, asset_id)
        _emit({"t": "tool_call", "id": "prep", "name": "make_video.preview",
               "args": {"prompt": prompt, "mode": mode, "duration": preview.get("params", {}).get("duration"),
                        "asset_id": asset_id}})
        if preview["errors"]:
            _emit({"t": "tool_result", "id": "prep", "ok": False,
                   "data": {"errors": preview["errors"]}})
            return {"intent": "chat",
                    "reply": "参数有问题：" + "；".join(preview["errors"]), "args": {}}
        _emit({"t": "tool_result", "id": "prep", "ok": True, "data": preview["params"]})
        return {"plan": {"kind": "video", **preview}}

    preview = tools.image_inputs_preview(
        prompt, str(args.get("aspect") or "9:16"),
        float(args["megapixels"]) if args.get("megapixels") else None,
        int(args.get("seed") or -1))
    _emit({"t": "tool_call", "id": "prep", "name": "make_image.preview",
           "args": {"prompt": prompt, "aspect": args.get("aspect"), "megapixels": args.get("megapixels")}})
    if preview["errors"]:
        _emit({"t": "tool_result", "id": "prep", "ok": False,
               "data": {"errors": preview["errors"]}})
        return {"reply": "参数有问题：" + "；".join(preview["errors"]),
                "intent": "chat", "args": {}}
    _emit({"t": "tool_result", "id": "prep", "ok": True, "data": preview["params"]})
    return {"plan": {"kind": "image", **preview}}


async def node_prepare_export(state: AgentState) -> dict:
    args = state.get("args") or {}
    project_id = state.get("project_id", "")
    quality = str(args.get("quality") or "1080p")
    if quality not in tools.QUALITY:
        quality = "1080p"
    preview = tools.export_preview(project_id, quality)
    _emit({"t": "tool_call", "id": "prep_export", "name": "make_film.preview",
           "args": {"quality": quality}})
    if not preview.get("ok"):
        _emit({"t": "tool_result", "id": "prep_export", "ok": False, "data": preview})
        return {"intent": "chat", "reply": "导不了：项目里还没有镜头。"}
    _emit({"t": "tool_result", "id": "prep_export", "ok": True, "data": preview})
    return {"plan": {"kind": "export", "params": preview}}


async def node_prepare_save(state: AgentState) -> dict:
    args = state.get("args") or {}
    thread_id = state.get("thread_id", "")
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        for artifact in agent_store.list_artifacts(thread_id, limit=10):
            if artifact["ref_id"].startswith("job_"):
                job_id = artifact["ref_id"]
                break
    if not job_id:
        return {"intent": "chat", "reply": "还没生成过东西，先让我出一张图或一段视频吧。"}

    job = store.get_job(job_id)
    if not job:
        return {"intent": "chat", "reply": "找不到那个任务，可能已经被删了。"}
    if job.get("shot_id"):
        return {"intent": "chat", "reply": "这个任务已经是镜头了，去剪辑页能看到。"}
    if job.get("status") != "succeeded":
        return {"intent": "chat", "reply": "它还没生成完，等成功了再存成镜头。"}

    title = str(args.get("title") or "").strip()
    plan = {"kind": "save_shot", "params": {"job_id": job_id, "title": title}}
    _emit({"t": "tool_call", "id": "prep_save", "name": "save_as_shot.preview",
           "args": {"job_id": job_id, "title": title}})
    _emit({"t": "tool_result", "id": "prep_save", "ok": True,
           "data": {"job_id": job_id, "title": title,
                    "preset": job.get("preset_id")}})
    return {"plan": plan}


async def node_confirm(state: AgentState) -> dict:
    plan = state.get("plan") or {}
    params = plan.get("params") or {}
    kind = plan.get("kind") or "image"
    mp_options = plan.get("megapixels_options") or []

    if kind == "export":
        summary = (f"{params.get('width')}×{params.get('height')} · {params.get('shots')} 镜 · "
                   f"约 {params.get('approx_seconds')} 秒 · 预计 {params.get('eta')} 秒出片")
        payload = {"kind": "confirm", "action": "export", "title": "导出成片",
                   "summary": summary, "params": params, "preset_id": "", "mode": ""}
    elif kind == "save_shot":
        payload = {"kind": "confirm", "action": "save_shot", "title": "存为镜头",
                   "summary": params.get("title") or "写入当前项目",
                   "params": params, "preset_id": "", "mode": ""}
    elif kind == "video":
        eta = max(60, int(float(params.get("duration") or 5) * 40))
        payload = {"kind": "confirm", "action": "video", "title": "生成视频",
                   "summary": f"{params.get('width')}×{params.get('height')} · {params.get('duration')} 秒 · 约 {eta} 秒",
                   "params": {**params, "megapixels_options": mp_options},
                   "mode": plan.get("mode", ""),
                   "preset_id": plan.get("preset_id")}
    else:
        payload = {"kind": "confirm", "action": "image", "title": "生成图片",
                   "summary": f"{params.get('width')}×{params.get('height')} · 约 40 秒",
                   "params": {**params, "megapixels_options": mp_options},
                   "mode": "", "preset_id": plan.get("preset_id")}


    decision = interrupt(payload) or {}
    approved = bool(decision.get("approved"))
    if not approved:
        return {"decision": "cancelled", "reply": "好，这次不生成。想改哪里直接说。", "intent": "chat"}

    # 确认卡上改过的参数（提示词 / 画幅 / 清晰度 / 时长）要真正生效
    edited = decision.get("params") or {}
    if isinstance(edited, dict) and edited:
        kind = plan.get("kind") or "image"
        merged = {**params, **edited}
        if kind == "video":
            fixed = tools.video_inputs_preview(
                str(merged.get("prompt") or ""), plan.get("mode", "t2v"),
                str(merged.get("aspect") or "16:9"),
                float(merged["duration"]) if merged.get("duration") else None,
                str(merged.get("image_asset_id") or ""),
                float(merged["megapixels"]) if merged.get("megapixels") else None)
        elif kind == "image":
            fixed = tools.image_inputs_preview(
                str(merged.get("prompt") or ""),
                str(merged.get("aspect") or "9:16"),
                float(merged["megapixels"]) if merged.get("megapixels") else None,
                int(merged.get("seed") or -1))
        else:
            fixed = {"params": merged}

        if fixed.get("errors"):
            return {"decision": "cancelled", "intent": "chat",
                    "reply": "这些参数不行：" + "；".join(fixed["errors"])}
        plan = {**plan, "params": {**merged, **fixed["params"]}}

    return {"decision": "approved", "plan": plan}


async def node_dispatch(state: AgentState) -> dict:
    plan = state.get("plan") or {}
    params = plan.get("params") or {}
    thread_id = state.get("thread_id", "")
    run_id = state.get("run_id", "")
    kind = plan.get("kind") or "image"
    if kind == "export":
        _emit({"t": "tool_call", "id": "gen", "name": "make_film",
               "args": {"quality": params.get("quality")}})
        raw = await tools.make_film(state.get("project_id", ""),
                                    str(params.get("quality") or "1080p"))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")),
               "data": {"render_id": data.get("render_id")}})
        if not data.get("ok"):
            return {"reply": f"导出失败：{data.get('hint') or data.get('error')}"}
        artifact = agent_store.add_artifact(run_id, thread_id, "render", data["render_id"], "",
                                            {"params": params, "status": "queued"})
        _emit({"t": "artifact", "kind": "render", "ref_id": data["render_id"],
               "artifact_id": artifact["id"], "url": ""})
        return {"reply": f"开始导出 {params.get('shots')} 个镜头，好了我把片子发过来。"}

    if kind == "save_shot":
        _emit({"t": "tool_call", "id": "gen", "name": "save_as_shot",
               "args": {"job_id": params.get("job_id"), "title": params.get("title")}})
        raw = await tools.save_as_shot(params.get("job_id", ""), state.get("project_id", ""),
                                       str(params.get("title") or ""))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        if not data.get("ok"):
            return {"reply": f"存不了：{data.get('hint') or data.get('error')}"}
        artifact = agent_store.add_artifact(run_id, thread_id, "shot", data["shot_id"], "",
                                            {"title": data.get("title")})
        _emit({"t": "artifact", "kind": "shot", "ref_id": data["shot_id"],
               "artifact_id": artifact["id"], "url": ""})
        return {"reply": f"已存成镜头「{data.get('title')}」，去剪辑页就能看到。"}

    is_video = kind == "video"
    if is_video:
        _emit({"t": "tool_call", "id": "gen", "name": "make_video",
               "args": {"prompt": params.get("prompt"), "mode": plan.get("mode"),
                        "duration": params.get("duration")}})
        raw = await tools.make_video(
            params.get("prompt", ""), plan.get("mode", "t2v"),
            params.get("aspect", "16:9"),
            float(params["duration"]) if params.get("duration") else None,
            str(params.get("image_asset_id") or ""),
            float(params["megapixels"]) if params.get("megapixels") else None)
    else:
        _emit({"t": "tool_call", "id": "gen", "name": "make_image",
               "args": {"prompt": params.get("prompt"), "aspect": params.get("aspect")}})
        raw = await tools.make_image(
            params.get("prompt", ""), params.get("aspect", "9:16"),
            params.get("megapixels"), int(params.get("seed") or -1))
    data = json.loads(raw)
    _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")),
                   "data": {"job_id": data.get("job_id")}})
    if not data.get("ok"):
        return {"reply": f"提交失败了：{data.get('hint') or data.get('error')}"}
    kind = "video" if is_video else "image"
    artifact = agent_store.add_artifact(run_id, thread_id, kind, data["job_id"], "",
                                  {"params": params, "status": "queued"})
    _emit({"t": "artifact", "kind": kind, "ref_id": data["job_id"],
                   "artifact_id": artifact["id"], "url": ""})
    return {"reply": f"已提交，任务 id {data['job_id']}。出图后我会把结果发过来。"}


def route_after_decide(state: AgentState) -> str:
    intent = state.get("intent") or "chat"
    if intent == "lookup":
        return "lookup"
    if intent in {"generate", "generate_video"}:
        return "prepare"
    if intent == "export":
        return "prepare_export"
    if intent == "save_shot":
        return "prepare_save"
    return "chat"


def route_after_prepare(state: AgentState) -> str:
    return "chat" if state.get("intent") == "chat" else "confirm"


def route_after_confirm(state: AgentState) -> str:
    return "dispatch" if state.get("decision") == "approved" else "chat"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("intake", node_intake)
    graph.add_node("decide", node_decide)
    graph.add_node("chat", node_chat)
    graph.add_node("lookup", node_lookup)
    graph.add_node("prepare", node_prepare)
    graph.add_node("prepare_export", node_prepare_export)
    graph.add_node("prepare_save", node_prepare_save)
    graph.add_node("confirm", node_confirm)
    graph.add_node("dispatch", node_dispatch)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "decide")
    graph.add_conditional_edges("decide", route_after_decide,
                                {"chat": "chat", "lookup": "lookup", "prepare": "prepare",
                                 "prepare_export": "prepare_export",
                                 "prepare_save": "prepare_save"})
    graph.add_edge("lookup", END)
    graph.add_conditional_edges("prepare", route_after_prepare,
                                {"chat": "chat", "confirm": "confirm"})
    graph.add_edge("prepare_export", "confirm")
    graph.add_edge("prepare_save", "confirm")
    graph.add_conditional_edges("confirm", route_after_confirm,
                                {"dispatch": "dispatch", "chat": "chat"})
    graph.add_edge("dispatch", END)
    graph.add_edge("chat", END)
    return graph.compile(checkpointer=MemorySaver())

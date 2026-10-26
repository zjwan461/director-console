"""LangGraph 编排：intake → decide → (chat | lookup | prepare) → 确认 → dispatch。

M1 的取舍：dispatch 之后立即结束 run，任务结果由 watch_job 作为「新消息」追加，
不把图挂在等待上——刷新页面、长任务、并发都不会互相拖累。
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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


VIDEO_RE = re.compile(r"(视频|动起来|动一下|动画|运镜|几秒|秒的片|短片|出片)")
IMAGE_RE = re.compile(r"(画|图|海报|剧照|插画|立绘|封面|定妆照)")
LOOKUP_RE = re.compile(r"(素材|找一?张|有没有.*图|看看.*图)")
EXPORT_RE = re.compile(r"(导出|合成|出成片|成片)")
SAVE_RE = re.compile(r"(存成?镜头|放进项目|存进项目|加入项目)")
DURATION_RE = re.compile(r"(\d+)\s*秒")


def _fast_intent(state: AgentState) -> dict | None:
    """常见说法直接判定意图，避免每次都等模型（推理模型要一两分钟）。

    只有真正模糊的（闲聊、改稿）才交给模型。
    """
    text = (state.get("text") or "").strip()
    if not text:
        return None

    ctx = agent_store.get_context(state.get("thread_id", ""))
    last_asset = str(ctx.get("last_asset_id") or "")
    duration_match = DURATION_RE.search(text)
    duration = int(duration_match.group(1)) if duration_match else 5

    POLISH_RE = re.compile(r"(字幕|旁白|配音|口播|解说|AI ?剪辑|一键剪辑)")
    BGM_RE = re.compile(r"(配乐|背景音乐|BGM|加.*音乐|音乐.*换|来点音乐)", re.IGNORECASE)
    FILM_RE = re.compile(r"(转场|片头|片尾|画幅|比例)")

    NEWPROJECT_RE = re.compile(r"(新建|建个|开个|创建).{0,4}项目|新项目")
    ADDSHOT_RE = re.compile(r"(加|添加|补|建).{0,3}(镜头|几镜|分镜)")

    if NEWPROJECT_RE.search(text):
        name_match = re.search(r"[叫名称为是]\s*[「《\"]([^」》\"]{1,20})", text)
        name = name_match.group(1) if name_match else text.strip()[:16]
        return {"intent": "create_project", "args": {"name": name},
                "reply": f"好，我新建一个项目《{name}》。"}
    if ADDSHOT_RE.search(text):
        return {"intent": "add_shot", "args": {"raw": text},
                "reply": "好，我按你的描述排几个镜头。"}
    if POLISH_RE.search(text):
        kinds = "narration" if "旁白" in text and "字幕" not in text else (
            "subtitle" if "字幕" in text and "旁白" not in text else "both")
        return {"intent": "polish", "args": {"kinds": kinds, "tts": "配音" in text or kinds != "subtitle"},
                "reply": "好，我来补文案和配音。"}
    if BGM_RE.search(text):
        mode = "off" if ("关掉" in text or "去掉" in text) else (
            "asset" if ("这首" in text or "那首" in text or "用" in text) else "auto")
        return {"intent": "bgm", "args": {"mode": mode, "query": text},
                "reply": "好，我来配乐。"}
    if EXPORT_RE.search(text):
        return {"intent": "export", "args": {}, "reply": "好，我按项目设置导出成片。"}
    if SAVE_RE.search(text):
        return {"intent": "save_shot", "args": {}, "reply": "好，把刚才的产物存成镜头。"}
    if LOOKUP_RE.search(text):
        return {"intent": "lookup", "args": {"q": "", "kind": "image"},
                "reply": "我去素材库里翻一下。"}
    if VIDEO_RE.search(text):
        mode = "i2v" if (last_asset and "首帧" in text) else "t2v"
        args = {"prompt": text, "mode": mode, "duration": duration, "aspect": "16:9"}
        if mode == "i2v":
            args["image_asset_id"] = last_asset
        return {"intent": "generate_video", "args": args,
                "reply": "好，我来生成这段视频。"}
    if IMAGE_RE.search(text):
        return {"intent": "generate", "args": {"prompt": text, "aspect": "9:16"},
                "reply": "好，我来出图。"}
    if FILM_RE.search(text):
        return {"intent": "film_options", "args": {"raw": text},
                "reply": "好，我改一下成片设置。"}
    return None


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
        # 产物可能比上下文早落库（watcher 还在轮询），从最近产物兜底
        for artifact in agent_store.list_artifacts(thread_id, limit=10):
            if artifact["kind"] == "image" and artifact["url"]:
                asset_id = tools.asset_from_url(artifact["url"], artifact["ref_id"])
                if asset_id:
                    agent_store.set_context(thread_id, {
                        "last_asset_id": asset_id, "last_kind": "image",
                        "last_job_id": artifact["ref_id"], "last_url": artifact["url"]})
                    break
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
    # 肯定回复优先于关键词：否则「可以，就用这张图」会被 图 字带走，重新出图
    shortcut = _short_circuit(state)
    if shortcut:
        _emit({"t": "step", "id": "decide", "node": "decide", "title": "接着上一步",
               "status": "done", "detail": {"intent": shortcut["intent"],
                                             "reason": "肯定回复 + 最近有产物"}})
        return {**shortcut, "decision": ""}

    fast = _fast_intent(state)
    if fast:
        _emit({"t": "step", "id": "decide", "node": "decide", "title": "理解需求",
               "status": "done", "detail": {"intent": fast["intent"], "fast": True,
                                             "args": fast.get("args")}})
        return fast

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
        import asyncio as _asyncio

        resp = await _asyncio.wait_for(llm.ainvoke(msgs), timeout=45)
        data = _parse_json(getattr(resp, "content", "") or "")
    except _asyncio.TimeoutError:
        return {"intent": "chat", "args": {},
                "reply": "模型响应有点慢，我先按最直接的理解处理：你想出图还是出视频？"}
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
        SystemMessage(content=prompts.chat_system_prompt(env, project_ctx)),
        *history[-12:],
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

    cleaned = text.strip()
    # 个别模型会照着系统提示里的 JSON 例子输出，兜底剥掉
    if cleaned.startswith("{") and '"intent"' in cleaned:
        parsed = _parse_json(cleaned)
        cleaned = str(parsed.get("reply") or "").strip() or fallback or "我在。"
    return {"reply": cleaned or fallback or "我在。", "streamed": True}


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


async def node_prepare_new_project(state: AgentState) -> dict:
    args = state.get("args") or {}
    name = str(args.get("name") or "未命名项目").strip()[:40]
    _emit({"t": "tool_call", "id": "prep_new", "name": "create_project", "args": {"name": name}})
    _emit({"t": "tool_result", "id": "prep_new", "ok": True, "data": {"name": name}})
    return {"plan": {"kind": "create_project", "params": {"name": name}}}


async def node_prepare_add_shot(state: AgentState) -> dict:
    args = state.get("args") or {}
    project_id = state.get("project_id", "")
    raw = str(args.get("raw") or state.get("text") or "")
    # 去掉「加三个镜头：」这类前缀，只留画面描述
    if any(sep in raw for sep in ("：", ":")):
        raw = re.split(r"[：:]", raw, maxsplit=1)[1]
    # 按“、，,;；/”切成几镜
    parts = [p.strip(" 。；;、") for p in re.split(r"[、，,;；/]|\s+和\s+", raw) if p.strip(" 。；;、")]
    prompts = [p for p in parts if len(p) >= 2][:8] or [raw.strip()]
    preview = tools.add_shot_preview(project_id, prompts)
    _emit({"t": "tool_call", "id": "prep_shot", "name": "add_shots.preview",
           "args": {"count": len(prompts)}})
    _emit({"t": "tool_result", "id": "prep_shot", "ok": True, "data": preview})
    return {"plan": {"kind": "add_shot", "params": {"prompts": prompts, "count": len(prompts)}}}


async def node_prepare_polish(state: AgentState) -> dict:
    args = state.get("args") or {}
    project_id = state.get("project_id", "")
    kinds = str(args.get("kinds") or "both")
    tts = bool(args.get("tts", True))
    preview = tools.polish_preview(project_id, kinds, tts, True)
    if not preview.get("shots"):
        return {"intent": "chat", "reply": "项目里还没有镜头，先出几镜再让我补文案。"}
    _emit({"t": "tool_call", "id": "prep_polish", "name": "polish_film.preview",
           "args": {"kinds": kinds, "tts": tts}})
    _emit({"t": "tool_result", "id": "prep_polish", "ok": True, "data": preview})
    return {"plan": {"kind": "polish", "params": preview}}


async def node_prepare_bgm(state: AgentState) -> dict:
    args = state.get("args") or {}
    project_id = state.get("project_id", "")
    mode = str(args.get("mode") or "auto")
    query = str(args.get("query") or "")
    preview = tools.bgm_preview(project_id, mode, query)
    _emit({"t": "tool_call", "id": "prep_bgm", "name": "set_bgm.preview",
           "args": {"mode": mode, "query": query}})
    if not preview.get("ok"):
        _emit({"t": "tool_result", "id": "prep_bgm", "ok": False, "data": preview})
        return {"intent": "chat", "reply": "；".join(preview.get("errors") or ["配乐不可用"])}
    _emit({"t": "tool_result", "id": "prep_bgm", "ok": True, "data": preview})
    return {"plan": {"kind": "bgm", "params": preview}}


async def node_prepare_film(state: AgentState) -> dict:
    args = state.get("args") or {}
    project_id = state.get("project_id", "")
    raw = str(args.get("raw") or "")
    transition, title, tail, aspect = "", "", "", ""
    if "淡入" in raw or "fade" in raw.lower():
        transition = "fade"
    elif "溶解" in raw or "交叉" in raw:
        transition = "dissolve"
    elif "硬切" in raw:
        transition = "none"
    if "竖屏" in raw:
        aspect = "9:16"
    elif "横屏" in raw:
        aspect = "16:9"
    title_match = re.search(r"片头[^「《\"]*[「《\"]([^」》\"]{1,20})", raw)
    if title_match:
        title = title_match.group(1)
    tail_match = re.search(r"片尾[^「《\"]*[「《\"]([^」》\"]{1,20})", raw)
    if tail_match:
        tail = tail_match.group(1)

    preview = tools.film_options_preview(project_id, transition, title, tail, aspect)
    _emit({"t": "tool_call", "id": "prep_film", "name": "set_film_options.preview",
           "args": {"transition": transition, "title": title, "tail": tail, "aspect": aspect}})
    _emit({"t": "tool_result", "id": "prep_film", "ok": True, "data": preview})
    return {"plan": {"kind": "film_options", "params": preview}}


async def node_confirm(state: AgentState) -> dict:
    plan = state.get("plan") or {}
    params = plan.get("params") or {}
    kind = plan.get("kind") or "image"
    mp_options = plan.get("megapixels_options") or []

    if kind == "export":
        extras = ["烧字幕" if params.get("subtitles") else "不烧字幕"]
        if params.get("bgm"):
            extras.append(f"{params['bgm']} 条 BGM")
        if params.get("title_seconds"):
            extras.append(f"片头 {params['title_seconds']}s")
        if params.get("tail_seconds"):
            extras.append(f"片尾 {params['tail_seconds']}s")
        summary = (f"{params.get('width')}×{params.get('height')} · {params.get('shots')} 镜 · "
                   f"约 {params.get('approx_seconds')} 秒 · {' · '.join(extras)} · 预计 {params.get('eta')} 秒")
        payload = {"kind": "confirm", "action": "export", "title": "导出成片",
                   "summary": summary, "params": params, "preset_id": "", "mode": ""}
    elif kind == "create_project":
        payload = {"kind": "confirm", "action": "create_project", "title": "新建项目",
                   "summary": f"项目名《{params.get('name')}》，并新开一个会话",
                   "params": params, "preset_id": "", "mode": ""}
    elif kind == "add_shot":
        payload = {"kind": "confirm", "action": "add_shot", "title": "加镜头",
                   "summary": f"新增 {params.get('count')} 个镜头（文生视频，5 秒）",
                   "params": params, "preset_id": "", "mode": ""}
    elif kind == "polish":
        kinds_label = {"both": "字幕 + 旁白", "subtitle": "只写字幕", "narration": "只写旁白"}.get(
            str(params.get("kinds")), "字幕 + 旁白")
        extras = [kinds_label]
        if params.get("tts"):
            extras.append("配音")
        if params.get("titles"):
            extras.append("片头片尾")
        payload = {"kind": "confirm", "action": "polish", "title": "AI 剪辑",
                   "summary": f"{params.get('shots')} 镜 · {' · '.join(extras)} · 预计 {params.get('eta')} 秒",
                   "params": params, "preset_id": "", "mode": ""}
    elif kind == "bgm":
        mode = str(params.get("mode") or "auto")
        if mode == "off":
            summary = "关掉背景音乐"
        elif mode == "asset":
            picked = params.get("picked") or {}
            summary = f"用这一首：{picked.get('name') or '素材库第一首'}"
        else:
            summary = "按段落自动配乐（开场/发展/收尾各一首）"
        payload = {"kind": "confirm", "action": "bgm", "title": "配乐",
                   "summary": summary, "params": params, "preset_id": "", "mode": mode}
    elif kind == "film_options":
        bits = []
        if params.get("transition"):
            bits.append(f"转场 {params['transition']}")
        if params.get("title"):
            bits.append(f"片头《{params['title']}》")
        if params.get("tail"):
            bits.append(f"片尾《{params['tail']}》")
        if params.get("aspect"):
            bits.append(f"画幅 {params['aspect']}")
        payload = {"kind": "confirm", "action": "film_options", "title": "成片设置",
                   "summary": " · ".join(bits) or "保持当前设置",
                   "params": params, "preset_id": "", "mode": ""}
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

    if kind == "create_project":
        _emit({"t": "tool_call", "id": "gen", "name": "create_project",
               "args": {"name": params.get("name")}})
        data = json.loads(tools.create_project(str(params.get("name") or "")))
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        if not data.get("ok"):
            return {"reply": "建项目失败了，稍后再试。"}
        _emit({"t": "switch_thread", "thread_id": data["thread_id"],
               "project_id": data["project_id"], "title": data["project_name"]})
        return {"reply": f"项目《{data['project_name']}》建好了，已经给你开好新会话，"
                         f"接着说想拍什么就行。"}

    if kind == "add_shot":
        _emit({"t": "tool_call", "id": "gen", "name": "add_shots",
               "args": {"count": params.get("count")}})
        raw = await tools.add_shots(state.get("project_id", ""), list(params.get("prompts") or []))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        if not data.get("ok"):
            return {"reply": f"加镜头没成功：{data.get('hint') or data.get('error')}"}
        lines = "、".join(item["title"] for item in data["created"])
        return {"reply": f"加了 {data['count']} 个镜头（{lines}）。可以让我逐镜出片，或者说「导出成片」。"}

    if kind == "polish":
        _emit({"t": "tool_call", "id": "gen", "name": "polish_film",
               "args": {"kinds": params.get("kinds"), "tts": params.get("tts")}})
        raw = await tools.polish_film(state.get("project_id", ""),
                                      str(params.get("kinds") or "both"),
                                      bool(params.get("tts", True)),
                                      bool(params.get("titles", True)))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        if not data.get("ok"):
            return {"reply": f"AI 剪辑没启动：{data.get('hint') or data.get('error')}"}
        artifact = agent_store.add_artifact(run_id, thread_id, "ai_edit",
                                            data["edit_run_id"], "", {"status": "running"})
        _emit({"t": "artifact", "kind": "ai_edit", "ref_id": data["edit_run_id"],
               "artifact_id": artifact["id"], "url": ""})
        return {"reply": f"AI 剪辑已开始（{params.get('shots')} 镜），跑完我把结果告诉你。"}

    if kind == "bgm":
        _emit({"t": "tool_call", "id": "gen", "name": "set_bgm",
               "args": {"mode": params.get("mode")}})
        raw = await tools.set_bgm(state.get("project_id", ""),
                                  str(params.get("mode") or "auto"),
                                  str(params.get("query") or ""))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        if not data.get("ok"):
            return {"reply": f"配乐没成功：{data.get('hint') or data.get('error')}"}
        if data.get("mode") == "asset":
            return {"reply": f"已配上《{data.get('name')}》，去剪辑页试听一下。"}
        if data.get("mode") == "off":
            return {"reply": "已经把背景音乐关掉了。"}
        return {"reply": f"已按段落配好 {data.get('tracks')} 段音乐。"}

    if kind == "film_options":
        _emit({"t": "tool_call", "id": "gen", "name": "set_film_options",
               "args": {"transition": params.get("transition"), "title": params.get("title")}})
        raw = await tools.set_film_options(state.get("project_id", ""),
                                           str(params.get("transition") or ""),
                                           str(params.get("title") or ""),
                                           str(params.get("tail") or ""),
                                           str(params.get("aspect") or ""))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        changed = "、".join(data.get("changed") or [])
        return {"reply": f"改好了：{changed}。" if changed else "没识别出要改哪一项。"}

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
    if intent == "polish":
        return "prepare_polish"
    if intent == "bgm":
        return "prepare_bgm"
    if intent == "film_options":
        return "prepare_film"
    if intent == "create_project":
        return "prepare_new_project"
    if intent == "add_shot":
        return "prepare_add_shot"
    return "chat"


def route_after_prepare(state: AgentState) -> str:
    return "chat" if state.get("intent") == "chat" else "confirm"


def route_after_confirm(state: AgentState) -> str:
    return "dispatch" if state.get("decision") == "approved" else "chat"


def build_graph(checkpointer=None):
    """checkpointer 由 runtime 注入（持久化到 SQLite）；不传则退化为内存版。"""
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()

    graph = StateGraph(AgentState)
    graph.add_node("intake", node_intake)
    graph.add_node("decide", node_decide)
    graph.add_node("chat", node_chat)
    graph.add_node("lookup", node_lookup)
    graph.add_node("prepare", node_prepare)
    graph.add_node("prepare_export", node_prepare_export)
    graph.add_node("prepare_save", node_prepare_save)
    graph.add_node("prepare_polish", node_prepare_polish)
    graph.add_node("prepare_bgm", node_prepare_bgm)
    graph.add_node("prepare_film", node_prepare_film)
    graph.add_node("prepare_new_project", node_prepare_new_project)
    graph.add_node("prepare_add_shot", node_prepare_add_shot)
    graph.add_node("confirm", node_confirm)
    graph.add_node("dispatch", node_dispatch)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "decide")
    graph.add_conditional_edges("decide", route_after_decide,
                                {"chat": "chat", "lookup": "lookup", "prepare": "prepare",
                                 "prepare_export": "prepare_export",
                                 "prepare_save": "prepare_save",
                                 "prepare_polish": "prepare_polish",
                                 "prepare_bgm": "prepare_bgm",
                                 "prepare_film": "prepare_film",
                                 "prepare_new_project": "prepare_new_project",
                                 "prepare_add_shot": "prepare_add_shot"})
    graph.add_edge("lookup", END)
    graph.add_conditional_edges("prepare", route_after_prepare,
                                {"chat": "chat", "confirm": "confirm"})
    graph.add_edge("prepare_export", "confirm")
    graph.add_edge("prepare_save", "confirm")
    graph.add_edge("prepare_polish", "confirm")
    graph.add_edge("prepare_bgm", "confirm")
    graph.add_edge("prepare_film", "confirm")
    graph.add_edge("prepare_new_project", "confirm")
    graph.add_edge("prepare_add_shot", "confirm")
    graph.add_conditional_edges("confirm", route_after_confirm,
                                {"dispatch": "dispatch", "chat": "chat"})
    graph.add_edge("dispatch", END)
    graph.add_edge("chat", END)
    return graph.compile(checkpointer=checkpointer)

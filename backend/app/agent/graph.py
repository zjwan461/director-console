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
    preapproved: bool


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
def _messages_as_dicts(messages) -> list[dict]:
    from ..llm import to_dicts

    return to_dicts(messages)


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


QUESTION_RE = re.compile(
    r"(你能|你会|你可以|有哪些|有什么|哪个|哪些|怎么|如何|为什么|是否|支持|"
    r"能不能|可不可以|可以吗|吗\?|流程|步骤|区别|介绍|说明)")
IMPERATIVE_RE = re.compile(
    r"(帮我|给我|替我|来(一|个|段|张)?|做(一|个|段)?|生成|画(一|张)?|拍(一|段)?|"
    r"出(一|个|张|段)?|导出|合成|加(一|个|些)?|配(一|点|个)?|存(成|为)?|新建|建(一|个)?|创建)")
CAPABILITY_TEXT = (
    "我能帮你做这些：\n"
    "· 出图：画一张雪夜剑客，竖屏\n"
    "· 出视频：做一个 5 秒的雪地奔跑视频（文生/图生/参考生都行）\n"
    "· 找素材：素材库里有什么猫的图\n"
    "· AI 剪辑：帮我补字幕和旁白（字幕/旁白/配音/调速/片头片尾）\n"
    "· 配乐：配点背景音乐，或者指定某一首\n"
    "· 成片设置：片头写《…》，用淡入转场\n"
    "· 导出：导出成片\n"
    "· 建项目/加镜头：新建一个项目叫《…》、加三个镜头：A，B，C"
)


VIDEO_RE = re.compile(r"(视频|动起来|动一下|动画|运镜|几秒|秒的片|短片|出片)")
IMAGE_RE = re.compile(r"(画|图|海报|剧照|插画|立绘|封面|定妆照)")
LOOKUP_RE = re.compile(
    r"(素材|找一?张|有没有.*图|看看.*图|"
    r"(有没有|有哪些|查一下|看看|列一下|给我看|生成好的|做好的|已有的|现成的)"
    r".{0,12}(视频|图片|图|素材|音频|音乐|镜头))")
ASSET_KIND_RE = [
    (re.compile(r"(视频|片子|成片)"), "video"),
    (re.compile(r"(音乐|音频|配音|bgm)", re.IGNORECASE), "audio"),
    (re.compile(r"(图片|图|照片|截图)"), "image"),
]
QUERY_RE = re.compile(r"(有没有|有哪些|查一下|看看|列一下|给我看|生成好的|做好的|已有的|现成的)")
EXPORT_RE = re.compile(r"(导出|合成|出成片|成片)")
SAVE_RE = re.compile(r"(存成?镜头|放进项目|存进项目|加入项目)")
DURATION_RE = re.compile(r"(\d+)\s*秒")


PATHISH_RE = re.compile(r"(^[\w./\\-]+\.(png|jpe?g|webp|mp4|mov|wav|mp3)$|^uploads/|^outputs/)")


def _clean_prompt(text: str, fallback: str = "") -> str:
    """把误当成提示词的文件路径剔除掉。"""
    value = (text or "").strip()
    if not value:
        return fallback
    if PATHISH_RE.search(value):
        return fallback
    return value


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
    BGM_RE = re.compile(r"(配乐|背景音乐|BGM|配.{0,6}音乐|音乐|来点音乐)", re.IGNORECASE)
    FILM_RE = re.compile(r"(转场|片头|片尾|画幅|比例)")

    NEWPROJECT_RE = re.compile(r"(新建|建个|开个|创建).{0,4}项目|新项目")
    ADDSHOT_RE = re.compile(r"(加|添加|补|建).{0,3}(镜头|几镜|分镜)")

    # 「还缺什么 / 体检 / 什么状态」→ 读项目实际情况再回答
    if re.search(r"(还缺|缺什么|差什么|体检|检查一下|什么状态|做到哪)", text):
        return {"intent": "audit", "args": {}, "reply": ""}

    # 问「项目里有几个镜头/都是什么」→ 直接读镜头列表
    if re.search(r"(几个|多少|有哪些|看看).{0,6}(镜头|分镜)|镜头.{0,4}(几个|多少)", text):
        return {"intent": "list_shots", "args": {}, "reply": ""}

    # 找素材优先：问句里也常带「有什么猫的图」「有没有生成好的视频」
    # 但「有哪些视频工作流」问的是能力卡，不是素材
    workflow_question = bool(re.search(r"(工作流|能力卡|卡片|预设|模型|节点)", text))
    if LOOKUP_RE.search(text) and not workflow_question:
        kind = next((k for pattern, k in ASSET_KIND_RE if pattern.search(text)), "")
        return {"intent": "lookup", "args": {"q": "", "kind": kind},
                "reply": "我去素材库里翻一下。"}

    # 问「有哪些/能不能/怎么做/…吗？」这类问题，不要当成生成任务
    asking = bool(re.search(r"(？|\?|怎么|如何|为什么|哪些|什么|支持|是否|能否|可以吗|吗[？?]?$)", text))
    command_hint = bool(re.match(r"^(帮我|给我|替我|劳驾)", text))
    # 手里有一张图、又在问「怎么做/你觉得呢」→ 给具体建议，而不是念能力清单
    ctx_now = agent_store.get_context(state.get("thread_id", ""))
    has_asset = bool(ctx_now.get("last_asset_id"))
    # 只对「手上这张图下一步怎么弄」给建议；问工作流/区别的仍走解释
    advice_like = bool(re.search(r"(你觉得|建议|下一步|接下来|怎么办|咋办)", text)) or bool(
        re.search(r"(这张|这个|它)", text) and re.search(r"(怎么做|怎么弄|能做什么|干什么)", text))
    if advice_like and has_asset and not re.search(r"(工作流|区别|能力卡|卡片)", text):
        return {"intent": "advise", "args": {"q": text}, "reply": ""}

    if asking and not command_hint:
        if (re.search(r"(工作流|能力卡|卡片|预设|模型|节点)", text)
                and not re.search(r"(区别|不一样|哪个|选哪|哪种|怎么|如何|用法)", text)):
            return {"intent": "list_presets", "args": {}, "reply": ""}
        # 其余问题（区别 / 怎么用 / 参数含义）统一走解释型问答，回答更具体
        return {"intent": "explain", "args": {"q": text}, "reply": ""}

    if NEWPROJECT_RE.search(text):
        name_match = re.search(r"[叫名称为是]\s*[「《\"]([^」》\"]{1,20})", text)
        name = name_match.group(1) if name_match else text.strip()[:16]
        return {"intent": "create_project", "args": {"name": name},
                "reply": f"好，我新建一个项目《{name}》。"}
    # 「把这张图放进第 2 镜当首帧」→ 图生视频，不是新增镜头
    if (re.search(r"第\s*\d+\s*镜", text)
            and re.search(r"(这张|刚才|上一张|这个图)", text)
            and re.search(r"(首帧|首图|当首帧|做成|塞进|放进|用作)", text)):
        ctx_now = agent_store.get_context(state.get("thread_id", ""))
        return {"intent": "generate_video",
                "args": {"prompt": "让这张图动起来，自然运镜，人物轻微动作",
                         "mode": "i2v", "aspect": "16:9",
                         "image_asset_id": str(ctx_now.get("last_asset_id") or "")},
                "reply": "好，拿这张图当首帧生成一段镜头。"}

    if ADDSHOT_RE.search(text):
        return {"intent": "add_shot", "args": {"raw": text},
                "reply": "好，我按你的描述排几个镜头。"}
    if POLISH_RE.search(text):
        kinds = "narration" if "旁白" in text and "字幕" not in text else (
            "subtitle" if "字幕" in text and "旁白" not in text else "both")
        return {"intent": "polish", "args": {"kinds": kinds, "tts": "配音" in text or kinds != "subtitle"},
                "reply": "好，我来补文案和配音。"}
    if re.search(r"(音频|录音|这段声音|这首歌)", text) and re.search(r"(背景音乐|配乐|当音乐|做音乐|bgm)", text, re.IGNORECASE):
        return {"intent": "bgm", "args": {"mode": "asset", "query": text},
                "reply": "好，把这段音频当背景音乐。"}
    if BGM_RE.search(text):
        mode = "off" if ("关掉" in text or "去掉" in text) else (
            "asset" if ("这首" in text or "那首" in text or "用" in text) else "auto")
        return {"intent": "bgm", "args": {"mode": mode, "query": text},
                "reply": "好，我来配乐。"}
    if EXPORT_RE.search(text):
        return {"intent": "export", "args": {}, "reply": "好，我按项目设置导出成片。"}
    if SAVE_RE.search(text):
        return {"intent": "save_shot", "args": {}, "reply": "好，把刚才的产物存成镜头。"}
    REVISE_RE = re.compile(r"(再\S{0,3}(亮|暗|快|慢)|更(亮|暗|快|慢)|改成|换成|调成|调整成|"
                           r"改一?下?|换一?下?|调整|慢一点|快一点|放慢|加快|时长.*秒|清晰度)")
    if FILM_RE.search(text):
        return {"intent": "film_options", "args": {"raw": text},
                "reply": "好，我改一下成片设置。"}
    if REVISE_RE.search(text):
        return {"intent": "revise", "args": {"raw": text},
                "reply": "好，我在上一版基础上改。"}
    if re.search(r"(对口型|口型|lip ?sync)", text, re.IGNORECASE):
        return {"intent": "generate_video",
                "args": {"prompt": text, "mode": "lipsync", "aspect": "16:9"},
                "reply": "好，用这张人像和这段音频做对口型。"}

    if VIDEO_RE.search(text) and IMPERATIVE_RE.search(text):
        # 判断用哪种视频卡：参考图 → r2v，明确说首帧/这张图 → i2v，否则 t2v
        has_ref = bool(last_asset) or bool(
            [a for a in (state.get("attachments") or []) if a.get("kind") == "image"])
        if re.search(r"(参考|参考图|照这张|按这张)", text) and has_ref:
            mode = "r2v"
        elif re.search(r"(首帧|这张图|这个图|用它|把这张|让这张)", text) and has_ref:
            mode = "i2v"
        else:
            mode = "t2v"

        # 整句只是命令（「参考这张图做个视频」）时，画面留给看图写运镜
        command_only = bool(re.search(r"(这张图|这个图|参考这张|用它|把这张|让这张)", text)) and not re.search(
            r"(雪|雨|风|光|夜|人物|镜头|奔跑|转身|站|坐|城市|森林|海|山|手|发)", text)
        prompt_text = "" if command_only else text

        args = {"prompt": prompt_text, "mode": mode, "duration": duration, "aspect": "16:9"}
        if mode in {"i2v", "r2v"}:
            args["image_asset_id"] = last_asset
        return {"intent": "generate_video", "args": args,
                "reply": "好，我来生成这段视频。"}
    if IMAGE_RE.search(text) and IMPERATIVE_RE.search(text):
        return {"intent": "generate", "args": {"prompt": text, "aspect": "9:16"},
                "reply": "好，我来出图。"}
    return None


AFFIRM_RE = re.compile(
    r"(可以|好的|好吧|好嘞|好|行|嗯|对|是的|继续|开始|就用|用这张|用那张|用这个|来吧|走起|ok|okay|yes)",
    re.IGNORECASE)
NEGATIVE_RE = re.compile(r"(不好|不要|别用|不用|取消|算了|重新|换一张|换个|先不)")

VIDEO_WORDS = ("视频", "动起来", "动一下", "动态", "运镜", "动画", "几秒", "秒的片子", "出片")


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

    # 「有没有生成好的视频」是查询，不是要生成
    if QUERY_RE.search(text):
        return None

    # 说「参考这张图」是要走参考生视频（r2v），别抢先判成 i2v
    if re.search(r"(参考|参考图|照这张|按这张)", text):
        return None

    video_intent = any(word in text for word in VIDEO_WORDS)
    if not (_is_affirmative(text) or video_intent):
        return None
    # 用户明确要图片/重新画时，不要抢
    if any(word in text for word in ("重新画", "再画", "生成图片", "换一张图")):
        return None

    # 留空 → prepare 阶段会用多模态模型看图写运镜
    prompt = _clean_prompt(str(ctx.get("last_prompt") or ""), "")
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
    # 只发了文件、没写文字：直接确认收到并引导，不要让模型说「没收到图片」
    text_only = str(state.get("text") or "").strip()
    files = state.get("attachments") or []
    if files and not text_only:
        images = [a for a in files if a.get("kind") == "image"]
        audios = [a for a in files if a.get("kind") == "audio"]
        if images:
            first = images[0]
            asset_id = tools.asset_from_url(str(first.get("url") or ""), "")
            if asset_id:
                agent_store.set_context(state.get("thread_id", ""), {
                    "last_asset_id": asset_id, "last_kind": "image",
                    "last_url": first.get("url") or "",
                    "last_prompt": "",
                })
            reply = "收到图片了。你想拿它做什么？做成视频、改画幅、还是存成镜头？"
            if audios:
                reply = "收到图片和音频了。要做对口型，还是把这段音频当背景音乐？"
            return {"intent": "chat", "reply": reply, "args": {}}
        if audios:
            seconds = await tools.audio_seconds(str(audios[0].get("id") or ""))
            hint = f"（约 {seconds:.1f} 秒）" if seconds else ""
            return {"intent": "chat",
                    "reply": f"收到音频{hint}。你打算把它当背景音乐、做对口型、还是配到某一镜做旁白？",
                    "args": {}}

    # 上一轮确认过的多步计划，依赖产物到位后继续执行（不再弹确认）
    if state.get("preapproved"):
        steps = list((state.get("args") or {}).get("steps") or [])
        if steps:
            _emit({"t": "step", "id": "decide", "node": "decide",
                   "title": f"继续执行剩余 {len(steps)} 步", "status": "done",
                   "detail": {"source": "preapproved"}})
            return {"intent": "multi", "args": {"steps": steps},
                    "reply": ""}

    # 复合请求（一句话多件事）先做规划：规则分句优先，判不出来才问模型
    text_in = str(state.get("text") or "")
    try:
        from . import planner as _planner

        if _planner.looks_compound(text_in):
            planned = await _planner.plan(text_in, state.get("thread_id", ""),
                                          state.get("project_id", ""))
            steps = planned.get("steps") or []
            if len(steps) >= 2:
                _emit({"t": "step", "id": "decide", "node": "decide",
                       "title": "拆成 " + str(len(steps)) + " 步", "status": "done",
                       "detail": {"source": planned.get("source"), "steps": [
                           {"tool": s["tool"], "why": s.get("why")} for s in steps]}})
                return {"intent": "multi", "args": {"steps": steps},
                        "reply": planned.get("reply") or "好，我按顺序做这几步。"}
    except Exception:
        pass

    # 疑问句先走问答：否则「你有哪些视频工作流」会被视频+最近产物短路成生成
    text_now = str(state.get("text") or "")
    asking = bool(re.search(r"(？|\?|怎么|如何|为什么|哪些|什么|支持|是否|能否|可以吗|吗[？?]?$)",
                            text_now))
    if asking and not re.match(r"^(帮我|给我|替我|劳驾)", text_now):
        fast_q = _fast_intent(state)
        if fast_q:
            return fast_q

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
        lines = []
        for att in attachments:
            name = str(att.get("path") or "").rsplit("/", 1)[-1]
            kind = str(att.get("kind") or "")
            if kind == "image":
                lines.append(f"- 图片：asset_id={att.get('id')}，文件 {name}")
            elif kind == "audio":
                seconds = await tools.audio_seconds(str(att.get("id") or ""))
                extra = f"，约 {seconds:.1f} 秒" if seconds else ""
                lines.append(f"- 音频：asset_id={att.get('id')}，文件 {name}{extra}")
        if lines:
            project_ctx = dict(project_ctx or {})
            project_ctx["用户随本条消息上传的文件（已经收到，不要说没收到）"] = lines

    from .. import llm as llm_module

    if not llm_module.ready():
        return {"intent": "chat",
                "reply": "还没配置大模型（设置 → AI），先配好我才能帮你出图。",
                "args": {}}

    # 规则没接住 → 交给 agentic 循环：模型可以查状态/素材，再决定做什么
    from . import agent_loop

    looped = await agent_loop.run(
        str(state.get("text") or ""), state.get("thread_id", ""),
        state.get("project_id", ""), state.get("attachments") or [])
    steps = looped.get("steps") or []
    reply = str(looped.get("reply") or "").strip()

    if len(steps) == 1:
        step = steps[0]
        _emit({"t": "step", "id": "decide", "node": "decide", "title": "理解需求",
               "status": "done",
               "detail": {"intent": step["intent"], "tool": step["tool"], "args": step["args"]}})
        return {"intent": step["intent"], "args": step.get("args") or {}, "reply": reply}

    if len(steps) > 1:
        _emit({"t": "step", "id": "decide", "node": "decide",
               "title": f"拆成 {len(steps)} 步", "status": "done",
               "detail": {"steps": [{"tool": s["tool"], "why": s.get("why")} for s in steps]}})
        return {"intent": "multi", "args": {"steps": steps}, "reply": reply}

    return {"intent": "chat", "args": {}, "reply": reply}


TOOL_LABEL = {
    "make_image": "出图",
    "make_video": "出视频",
    "revise": "修订上一版",
    "lookup_assets": "查素材",
    "export_film": "导出成片",
    "polish_film": "AI 剪辑（字幕/旁白）",
    "set_bgm": "配乐",
    "set_film_options": "成片设置",
    "create_project": "建项目",
    "add_shots": "加镜头",
}

FAQ = [
    (r"(图生视频|图做视频|图片.*视频|首帧|用这张图)", (
        "图生视频两步：\n"
        "1. 先说「画一张…」出图（或者上传一张图）\n"
        "2. 说「可以，就用这张图」——我会拿它当首帧生成视频\n"
        "也可以在确认卡里调时长和清晰度。")),
    (r"(文生视频|直接.*视频|t2v)", (
        "说一句画面就行：「做一个 5 秒的雪地奔跑视频，横屏」。\n"
        "我会先弹确认卡，确认后才提交。")),
    (r"(参考|r2v|多图)", (
        "参考生视频：先在创作台上传参考图，然后说「参考这张图做一个视频」，\n"
        "最多可以给我 9 张参考图。")),
    (r"(字幕|旁白|口播|配音)", (
        "说「帮我补字幕和旁白」，我会按每镜的画面写文案，\n"
        "有旁白的话字幕会跟着旁白走，还能自动配音和调速。")),
    (r"(配乐|音乐|bgm)", (
        "说「配点背景音乐」我会按开场/发展/收尾自动配；\n"
        "想指定就说「用那首治愈的」，想关掉说「把音乐去掉」。")),
    (r"(导出|成片|渲染)", (
        "说「导出成片」或「导出 720p」，确认卡会列出镜数、是否烧字幕、几条 BGM、片头片尾时长。")),
    (r"(建项目|新项目|新建)", (
        "说「新建一个项目叫《雪夜归人》」，我会建项目并自动开一个新会话。")),
    (r"(分辨率|清晰度|多少像素|多大尺寸)", (
        "分辨率在确认卡里选：图片 0.8~2.0 MP，视频 0.4/0.8 MP，\n"
        "画幅决定形状（9:16 竖屏 / 16:9 横屏），旁边会实时显示换算后的像素。")),
    (r"(时长|几秒|多长)", (
        "视频时长在确认卡里选（3~15 秒），实际会按 24fps 取 4n+1 帧，\n"
        "所以 5 秒实际是 5.17 秒左右。")),
    (r"(加.*镜头|分镜|三镜|几个镜头)", (
        "说「加三个镜头：雪夜山门，蓝衣女子推门，她回身望向红灯」，\n"
        "我会按逗号拆成镜头并写好每镜的画面描述。")),
]


async def node_quick_reply(state: AgentState) -> dict:
    """本地已经算好的回复（提示/澄清），不调模型，秒回。"""
    reply = str(state.get("reply") or "").strip()
    _emit({"t": "step", "id": "decide", "node": "decide", "title": "需要确认一下",
           "status": "done", "detail": {"reply": reply[:80]}})
    return {"reply": reply or "我没太听懂，换个说法？", "streamed": False}


OPERATION_FACTS = """\n操作方式（可直接引用这里的说法）：
- 图生视频：先说「画一张…」出图，再说「可以，就用这张图」，这张图会当首帧
- 文生视频：直接说「做一个 5 秒的…视频」
- 参考生视频：先说「参考这张图做一个视频」，最多 9 张参考图
- 补字幕/旁白：说「帮我补字幕和旁白」，旁白写了字幕会跟着旁白走，可自动配音和调速
- 配乐：说「配点背景音乐」按开场/发展/收尾自动配；指定某首说「用那首治愈的」；关掉说「把音乐去掉」
- 导出：说「导出成片」或「导出 720p」，确认卡会列出镜数、是否烧字幕、几条 BGM、片头片尾时长
- 建项目：说「新建一个项目叫《雪夜归人》」
- 加镜头：说「加三个镜头：A，B，C」，系统按逗号拆成镜头
- 改上一版：说「第 2 张再亮一点」「时长改成 8 秒」「换成竖屏」，会基于那一版改，不重新写提示词
- 分辨率：图片 0.8~2.0 MP，视频 0.4/0.8 MP，画幅决定形状（9:16 竖屏 / 16:9 横屏）
- 时长：视频 3~15 秒，按 24fps 取 4n+1 帧，5 秒实际约 5.17 秒"""


def _card_facts() -> str:
    """把能力卡整理成事实清单，供「解释型」问答使用。"""
    lines = []
    for card in tools.load_cards():
        if not card.get("_workflow_exists"):
            continue
        public = tools.public_card(card)
        kind = {"video": "视频", "image": "图片"}.get(public.get("output_kind"), "其他")
        desc = str(public.get("desc") or "").strip()
        lines.append(f"- {public.get('name')}（{kind}）：{desc}")
        fields = public.get("fields") or []
        labels = [str(f.get("label")) for f in fields if f.get("label")]
        if labels:
            lines.append(f"  可调参数：{'、'.join(labels[:6])}")
    return ("\n".join(lines) or "（没有可用的能力卡）") + OPERATION_FACTS


EXPLAIN_SYSTEM = """你是导演台的能力顾问，只根据下面这份「能力卡事实」回答问题。

事实：
{facts}

要求：
1. 只用事实里出现的信息，不要编造工作流或参数
2. 用户问「怎么做/怎么用」时，给可执行的步骤，可以直接引用「操作方式」里的说法
3. 用户问「有什么区别」时，点出关键差异（输入形式、时长、参考图数量、适用场景）
4. 3~6 句中文，先给结论；不要输出 JSON，不要罗列全部卡片"""


ADVISE_SYSTEM = """你是导演台的现场助手。用户刚上传/生成了一张图片，正在问接下来怎么做。

可用能力（只根据这些给建议）：
{facts}

要求：
1. 给 2~3 个具体可选方案，每个一句话，写清楚「会得到什么」
2. 最后一句给出你的推荐，并等用户确认（不要自己开始执行）
3. 不要罗列全部工作流，不要输出 JSON"""


async def node_advise(state: AgentState) -> dict:
    """有素材在手时给「下一步」建议，回答要具体、可执行。"""
    from .. import llm as llm_module

    question = str((state.get("args") or {}).get("q") or state.get("text") or "")
    facts = _card_facts()
    if not llm_module.ready():
        return {"reply": "还没配置大模型（设置 → AI）。可以先说「做成 5 秒视频」或「第 1 张再亮一点」。"}

    msgs = [
        {"role": "system", "content": ADVISE_SYSTEM.format(facts=facts)},
        {"role": "user", "content": question or "你觉得这张图接下来怎么做比较好？"},
    ]
    text = ""
    try:
        async for event in llm_module.chat_stream(msgs, temperature=0.4):
            delta = str(event.get("text") or "")
            if not delta:
                continue
            if event.get("type") == "reasoning":
                _emit({"t": "thinking", "text": delta})
                continue
            text += delta
            _emit({"t": "message_delta", "text": delta})
    except Exception as exc:
        return {"reply": f"给建议时出错了：{exc}"}
    return {"reply": text.strip() or "可以说「做成视频」或「再亮一点」，我来执行。", "streamed": True}


async def node_explain(state: AgentState) -> dict:
    """解释型问答：基于真实能力卡回答「区别/怎么选」。"""
    from .. import llm as llm_module

    question = str((state.get("args") or {}).get("q") or state.get("text") or "")
    facts = _card_facts()

    if not llm_module.ready():
        return {"reply": "还没配置大模型（设置 → AI）。先给你看当前可用的：\n" + facts}

    msgs = [
        {"role": "system", "content": EXPLAIN_SYSTEM.format(facts=facts)},
        {"role": "user", "content": question},
    ]
    text = ""
    try:
        async for event in llm_module.chat_stream(msgs, temperature=0.3):
            delta = str(event.get("text") or "")
            if not delta:
                continue
            if event.get("type") == "reasoning":
                _emit({"t": "thinking", "text": delta})
                continue
            text += delta
            _emit({"t": "message_delta", "text": delta})
    except Exception as exc:
        return {"reply": f"解释失败：{exc}", "streamed": False}

    return {"reply": text.strip() or "这几张卡的说明我这边没有更细的信息。", "streamed": True}


async def node_reply_capability(state: AgentState) -> dict:
    """能力介绍、工作流清单这类问题，直接用本地数据回答，不再等模型。"""
    if state.get("intent") == "list_presets":
        cards = [c for c in tools.load_cards() if c.get("_workflow_exists")]
        lines = []
        for card in cards:
            public = tools.public_card(card)
            kind = {"video": "视频", "image": "图片"}.get(public.get("output_kind"), "其他")
            lines.append(f"· {public.get('name')}（{kind}）")
        reply = "当前可用工作流：\n" + "\n".join(lines) + "\n\n想用哪个直接说画面内容就行。"
    else:
        text = str(state.get("text") or "")
        reply = prompts.CAPABILITY_TEXT
        for pattern, answer in FAQ:
            if re.search(pattern, text):
                reply = answer
                break
    _emit({"t": "step", "id": "decide", "node": "decide", "title": "理解需求",
           "status": "done", "detail": {"intent": state.get("intent"), "fast": True}})
    return {"reply": reply}


async def node_chat(state: AgentState) -> dict:
    """闲聊/解释走这里：真流式输出，前端能一个字一个字看到。"""
    from .. import llm as llm_module

    fallback = state.get("reply") or ""
    if not llm_module.ready():
        return {"reply": fallback or "还没配置大模型（设置 → AI）。"}

    env = json.loads(tools.env_check())
    env.pop("presets", None)
    project = store.get_project(state.get("project_id", "")) or {}
    shots = store.list_shots(state.get("project_id", "")) if project else []
    project_ctx = {**project, "shot_count": len(shots)} if project else None

    history = [m for m in state.get("messages", []) if isinstance(m, (HumanMessage, AIMessage))]
    msgs = llm_module.to_dicts([
        SystemMessage(content=prompts.chat_system_prompt(env, project_ctx)),
        *history[-12:],
    ])

    text = ""
    try:
        async for event in llm_module.chat_stream(msgs, temperature=0.4):
            delta = str(event.get("text") or "")
            if not delta:
                continue
            if event.get("type") == "reasoning":
                # 思考过程单独推给前端，前端边等边显示，不至于干等
                _emit({"t": "thinking", "text": delta})
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


async def node_audit(state: AgentState) -> dict:
    """片子体检：按项目实际数据列出「有什么、缺什么」。"""
    project_id = state.get("project_id", "")
    shots = store.list_shots(project_id) if project_id else []
    state_data = tools._edit_state(project_id) if project_id else {}
    options = state_data.get("options") or {}
    edits = state_data.get("shot_edits") or []

    with_cover = [s for s in shots if s.get("cover") or s.get("last_frame")]
    narration = sum(1 for e in edits if e.get("narration_on"))
    subtitles = sum(1 for e in edits if (e.get("narration") or e.get("subtitle")))
    bgm = len(options.get("bgm_tracks") or [])
    burned = bool((options.get("subtitles") or {}).get("enabled"))
    title_on = bool((options.get("title") or {}).get("enabled"))
    tail_on = bool((options.get("tail") or {}).get("enabled"))
    renders = store.list_renders(project_id, limit=5) if project_id else []
    exported = any(r.get("status") == "succeeded" for r in renders)

    lines = [f"项目现状：{len(shots)} 个镜头，{len(with_cover)} 个已有画面"]
    if narration:
        lines.append(f"· 旁白：{narration} 镜已写")
    if subtitles:
        lines.append(f"· 字幕：{subtitles} 镜有文案" + ("（导出会烧进画面）" if burned else ""))
    if bgm:
        lines.append(f"· 配乐：{bgm} 条")
    if title_on or tail_on:
        bits = []
        if title_on:
            bits.append("片头")
        if tail_on:
            bits.append("片尾")
        lines.append("· " + " + ".join(bits) + "：已开启")
    if exported:
        lines.append("· 成片：已经导出过一版")

    todo = []
    if not shots:
        todo.append("先加镜头：「加三个镜头：A，B，C」")
    elif len(with_cover) < len(shots):
        todo.append(f"还有 {len(shots) - len(with_cover)} 个镜头没画面，可以让我逐镜出片")
    if shots and not narration:
        todo.append("没有旁白/字幕：「帮我补字幕和旁白」")
    if shots and not bgm:
        todo.append("没有配乐：「配点背景音乐」")
    if shots and not (title_on or tail_on):
        todo.append("片头片尾还没开：「片头写《…》」")
    if shots and with_cover and not exported:
        todo.append("还没导出过：「导出成片」")

    reply = "\n".join(lines)
    if todo:
        reply += "\n\n建议下一步：\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(todo[:3], 1))
    else:
        reply += "\n\n基本齐了，可以直接「导出成片」。"
    _emit({"t": "step", "id": "audit", "node": "decide", "title": "项目体检",
           "status": "done", "detail": {"shots": len(shots), "covered": len(with_cover)}})
    return {"intent": "chat", "reply": reply}


async def node_list_shots(state: AgentState) -> dict:
    project_id = state.get("project_id", "")
    shots = store.list_shots(project_id) if project_id else []
    if not shots:
        return {"intent": "chat",
                "reply": "这个项目还没有镜头。可以先说「加三个镜头：A，B，C」，或者让我出一张图再存成镜头。"}
    lines = []
    for index, shot in enumerate(shots, start=1):
        title = shot.get("title") or f"镜头 {index}"
        cover = "有画面" if shot.get("cover") else "还没画面"
        duration = (shot.get("values") or {}).get("duration")
        extra = f" · {duration}s" if duration else ""
        lines.append(f"{index}. {title}（{cover}{extra}）")
    reply = f"项目里一共 {len(shots)} 个镜头：\n" + "\n".join(lines)
    _emit({"t": "step", "id": "shots", "node": "decide", "title": "读取镜头列表",
           "status": "done", "detail": {"count": len(shots)}})
    return {"intent": "chat", "reply": reply}


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
    prompt = _clean_prompt(str(args.get("prompt") or ""))
    # 视频可以「看图写运镜」，所以空提示词只对出图直接拦截
    if not prompt and intent != "generate_video":
        return {"intent": "chat", "reply": "能再说清楚一点画面内容吗？我好照着画。"}

    if intent == "generate_video":
        mode = str(args.get("mode") or "t2v").strip()
        if mode not in tools.VIDEO_CARDS:
            mode = "t2v"
        asset_id = str(args.get("image_asset_id") or "").strip()

        # 参考图优先级：本条附件 > 会话最近产物 > 素材库搜索
        if not asset_id:
            for att in state.get("attachments") or []:
                if att.get("kind") == "image":
                    asset_id = str(att.get("id") or "")
                    break
        if not asset_id and mode in {"i2v", "r2v", "lipsync", "r2v9"}:
            ctx_now = agent_store.get_context(state.get("thread_id", ""))
            if str(ctx_now.get("last_kind") or "") == "image":
                asset_id = str(ctx_now.get("last_asset_id") or "")

        # 没带图就去素材库找
        if mode in {"i2v", "r2v", "lipsync", "r2v9"} and not asset_id:
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

        # 音频：附件优先（可多段），其次 args 里指定的
        audio_ids = [str(att.get("id") or "") for att in (state.get("attachments") or [])
                     if att.get("kind") == "audio"]
        if args.get("audio_asset_id"):
            audio_ids = [str(args["audio_asset_id"])]
        elif args.get("audio_asset_ids"):
            audio_ids = [str(x) for x in args["audio_asset_ids"]]
        audio_ids = [x for x in audio_ids if x][:3]
        audio_id = audio_ids[0] if audio_ids else ""

        # 图生视频/参考生视频：没有具体提示词时，看图写运镜（这才是 agent 该干的事）
        # 需要「看图写运镜」的情况：没有提示词、只有默认句、或整句只是「参考这张图做个视频」这类命令
        commandish = bool(prompt) and bool(
            re.search(r"(这张图|这个图|参考这张|用它|把这张|参考图)", prompt)
            and not re.search(r"(雪|雨|风|光|夜|人物|镜头|奔跑|转身|站|坐|城市|森林|海|山)", prompt))
        if (mode in {"i2v", "r2v", "r2v9"} and asset_id
                and (not prompt or prompt == tools.DEFAULT_MOTION_PROMPT
                     or prompt.startswith("让这张图动起来") or commandish)):
            try:
                generated = await tools.motion_prompt(asset_id, str(state.get("text") or ""))
                if generated:
                    prompt = generated if not prompt or commandish else f"{prompt.rstrip('。')}，{generated}"
                    _emit({"t": "step", "id": "motion", "node": "prepare",
                           "title": "看图写运镜", "status": "done",
                           "detail": {"prompt": generated}})
            except Exception:
                pass

        # 「做成视频」这种只有动作没有画面描述的，看图补完后再判断
        if not prompt or not prompt.strip():
            return {"intent": "chat", "reply": "能再说清楚一点画面内容吗？我好照着拍。"}

        # 对口型：默认按音频时长出片，避免画面比声音长/短
        seconds = float(args["duration"]) if args.get("duration") else None
        if mode == "lipsync" and audio_id and not seconds:
            audio_len = await tools.audio_seconds(audio_id)
            if audio_len > 0:
                seconds = audio_len
                _emit({"t": "step", "id": "audio_len", "node": "prepare",
                       "title": f"按音频长度出片 {audio_len:.1f}s", "status": "done",
                       "detail": {"audio_asset_id": audio_id}})

        preview = tools.video_inputs_preview(
            prompt, mode, str(args.get("aspect") or ""), seconds, asset_id,
            None, audio_id, audio_ids)
        _emit({"t": "tool_call", "id": "prep", "name": "make_video.preview",
               "args": {"prompt": prompt, "mode": mode,
                        "duration": preview.get("params", {}).get("duration"),
                        "asset_id": asset_id, "audio_asset_id": audio_id}})
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


def _prepare_for(intent: str):
    """多步执行时按意图选对应的 prepare 节点（图里是不同节点，这里手动分派）。"""
    return {
        "generate": node_prepare,
        "generate_video": node_prepare,
        "revise": node_prepare_revise,
        "export": node_prepare_export,
        "save_shot": node_prepare_save,
        "polish": node_prepare_polish,
        "bgm": node_prepare_bgm,
        "film_options": node_prepare_film,
        "create_project": node_prepare_new_project,
        "add_shot": node_prepare_add_shot,
    }.get(intent, node_prepare)


def _multi_step_state(state: AgentState, step: dict) -> AgentState:
    """把某一步包装成一次单步执行所需的状态。"""
    return {
        **state,
        "intent": step["intent"],
        "args": step.get("args") or {},
        "text": step.get("text") or state.get("text") or "",
        "plan": None,
    }


async def node_prepare_multi(state: AgentState) -> dict:
    """多步计划：确认卡上把所有步骤列清楚，一步确认。"""
    args = state.get("args") or {}
    steps = list(args.get("steps") or [])
    if not steps:
        return {"intent": "chat", "reply": "我没拆出可执行的动作，能再说具体一点吗？"}

    previews = []
    for step in steps:
        args = dict(step.get("args") or {})
        previews.append({
            "index": step.get("index"),
            "tool": step["tool"],
            "intent": step["intent"],
            "label": TOOL_LABEL.get(step["tool"], step["tool"]),
            "why": step.get("why") or "",
            "depends_on": step.get("depends_on"),
            "text": step.get("text") or "",
            # 只暴露可读可改的字段，避免把内部结构塞给前端
            "args": {k: v for k, v in args.items()
                     if k in ("prompt", "aspect", "duration", "megapixels", "mode",
                              "quality", "kinds", "tts", "title", "relation")},
        })
    _emit({"t": "tool_call", "id": "prep_multi", "name": "plan.preview",
           "args": {"count": len(previews)}})
    _emit({"t": "tool_result", "id": "prep_multi", "ok": True,
           "data": {"steps": previews}})
    return {"plan": {"kind": "multi", "params": {"steps": steps, "previews": previews}}}


async def node_dispatch_multi(state: AgentState) -> dict:
    """按顺序执行：独立步骤立刻做，依赖前一步产物的先停住并说明。"""
    plan = state.get("plan") or {}
    steps = list((plan.get("params") or {}).get("steps") or [])
    replies: list[str] = []
    deferred: list[dict] = []
    done = 0

    preapproved = bool(state.get("preapproved"))
    for step in steps:
        # 预授权续跑时依赖已经满足（上一轮产物已就绪），不再延后
        if step.get("depends_on") and not preapproved:
            deferred.append(step)
            break

        sub = _multi_step_state(state, step)
        prepare_fn = _prepare_for(step["intent"])
        prepared = await prepare_fn(sub)
        if prepared.get("intent") == "chat":
            replies.append(f"第 {step['index']} 步跳过：{prepared.get('reply')}")
            continue
        sub["plan"] = prepared.get("plan")
        result = await node_dispatch(sub)
        done += 1
        replies.append(str(result.get("reply") or ""))

    if deferred:
        try:
            agent_store.set_context(state.get("thread_id", ""), {"pending_steps": deferred})
        except Exception:
            pass
        replies.append(f"还有 {len(deferred)} 步要用到上一步的产物，等它出来我再接着做。")

    return {"reply": "\n".join(r for r in replies if r) or "这几步都没能执行。"}


async def node_prepare_revise(state: AgentState) -> dict:
    args = state.get("args") or {}
    text = str(args.get("raw") or state.get("text") or "")
    preview = tools.revise_preview(state.get("thread_id", ""), state.get("project_id", ""), text)
    _emit({"t": "tool_call", "id": "prep_revise", "name": "revise.preview",
           "args": {"text": text}})
    if not preview.get("ok"):
        _emit({"t": "tool_result", "id": "prep_revise", "ok": False, "data": preview})
        return {"intent": "chat", "reply": preview.get("hint") or "没找到要改的那一版"}

    # 图片修订：让视觉模型把「太乱/改横屏」翻译成具体改动
    if preview.get("base_kind") == "image" and preview.get("base_url"):
        asset_id = tools.asset_from_url(str(preview["base_url"]), "")
        if asset_id:
            aspect = str((preview.get("patch") or {}).get("aspect") or "")
            guidance = await tools.vision_patch(asset_id, text, aspect)
            if guidance:
                params = dict(preview.get("params") or {})
                base_prompt = str(params.get("prompt") or "")
                keyword = str((preview.get("patch") or {}).get("prompt_suffix") or "")
                merged = "，".join(x for x in (base_prompt, keyword, guidance) if x)
                params["prompt"] = merged
                preview = {**preview, "params": params,
                           "patch": {**(preview.get("patch") or {}), "prompt_suffix": guidance},
                           "summary": f"{preview.get('summary')}｜看图：{guidance}"}
                _emit({"t": "step", "id": "vision_patch", "node": "prepare",
                       "title": "看图理解改动", "status": "done",
                       "detail": {"guidance": guidance}})

    _emit({"t": "tool_result", "id": "prep_revise", "ok": True, "data": preview})
    return {"plan": {"kind": "revise", "params": preview}}


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

    # 消息里带了音频，且用户说「当背景音乐」→ 直接用这条
    asset_id = str(args.get("asset_id") or "")
    if not asset_id and mode == "asset":
        for att in state.get("attachments") or []:
            if att.get("kind") == "audio":
                asset_id = str(att.get("id") or "")
                break

    preview = tools.bgm_preview(project_id, mode, query, asset_id)
    _emit({"t": "tool_call", "id": "prep_bgm", "name": "set_bgm.preview",
           "args": {"mode": mode, "query": query}})
    if not preview.get("ok"):
        _emit({"t": "tool_result", "id": "prep_bgm", "ok": False, "data": preview})
        return {"intent": "chat", "reply": "；".join(preview.get("errors") or ["配乐不可用"])}
    _emit({"t": "tool_result", "id": "prep_bgm", "ok": True, "data": preview})
    preview = {**preview, "asset_id": asset_id}
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
    elif kind == "multi":
        previews = params.get("previews") or []
        lines = []
        for item in previews:
            mark = "（等上一步产物）" if item.get("depends_on") else ""
            args = item.get("args") or {}
            bits = []
            if args.get("prompt"):
                bits.append(str(args["prompt"])[:18])
            if args.get("aspect"):
                bits.append(str(args["aspect"]))
            if args.get("duration"):
                bits.append(f"{args['duration']}s")
            if args.get("mode"):
                bits.append(str(args["mode"]))
            tail = f" · {' / '.join(bits)}" if bits else ""
            lines.append(f"{item.get('index')}. {item.get('label') or item.get('tool')}{mark}{tail}")
        payload = {"kind": "confirm", "action": "multi", "title": f"{len(previews)} 步计划",
                   "summary": " → ".join(lines) or "多步执行",
                   "params": params, "preset_id": "", "mode": "multi"}
    elif kind == "revise":
        payload = {"kind": "confirm", "action": "revise", "title": "修改上一版",
                   "summary": f"基于 #{params.get('base_ref')} · {params.get('summary')}",
                   "params": params, "preset_id": "", "mode": params.get("base_kind", "")}
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
        card = tools.get_card(str(plan.get("preset_id") or "")) or {}
        payload = {"kind": "confirm", "action": "video", "title": "生成视频",
                   "summary": f"{params.get('width')}×{params.get('height')} · {params.get('duration')} 秒 · 约 {eta} 秒",
                   "params": {**params, "megapixels_options": mp_options},
                   "mode": plan.get("mode", ""),
                   "preset_id": plan.get("preset_id"),
                   "preset_name": str(card.get("name") or ""),
                   "preset_id_label": str(plan.get("preset_id") or "")}
    else:
        card = tools.get_card(str(plan.get("preset_id") or "")) or {}
        payload = {"kind": "confirm", "action": "image", "title": "生成图片",
                   "summary": f"{params.get('width')}×{params.get('height')} · 约 40 秒",
                   "params": {**params, "megapixels_options": mp_options},
                   "mode": "", "preset_id": plan.get("preset_id"),
                   "preset_name": str(card.get("name") or "")}


    decision = interrupt(payload) or {}
    approved = bool(decision.get("approved"))
    if not approved:
        return {"decision": "cancelled", "intent": "chat",
                "reply": "已取消，这次没有提交。想调整参数或换个说法，直接告诉我就行。"}

    # 确认卡上改过的参数（提示词 / 画幅 / 清晰度 / 时长）要真正生效
    edited = decision.get("params") or {}
    if isinstance(edited, dict) and edited.get("steps") and plan.get("kind") == "multi":
        # 前端在多步卡上改过参数：以它为准
        merged_steps = edited["steps"]
        plan = {**plan, "params": {**params, "steps": merged_steps,
                                   "previews": edited.get("previews") or params.get("previews") or []}}
        return {"decision": "approved", "plan": plan}

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

    if kind == "revise":
        base = params or {}
        _emit({"t": "tool_call", "id": "gen", "name": "make_revision",
               "args": {"base_ref": base.get("base_ref"), "patch": base.get("patch")}})
        raw = await tools.make_revision(thread_id, state.get("project_id", ""),
                                        str(state.get("text") or ""))
        data = json.loads(raw)
        _emit({"t": "tool_result", "id": "gen", "ok": bool(data.get("ok")), "data": data})
        if not data.get("ok"):
            return {"reply": f"改不了：{data.get('hint') or data.get('error')}"}
        revision = data.get("revision") or {}
        rev_params = data.get("params") or {}
        rev_kind = "video" if revision.get("base_kind") == "video" else "image"
        artifact = agent_store.add_artifact(
            run_id, thread_id, rev_kind, data["job_id"], "",
            {"params": rev_params, "status": "queued",
             "parent_ref": revision.get("base_ref"), "note": revision.get("note", "")})
        _emit({"t": "artifact", "kind": rev_kind, "ref_id": data["job_id"],
               "artifact_id": artifact["id"], "url": ""})
        return {"reply": f"基于 #{revision.get('base_ref')} 改了一版："
                         f"{revision.get('summary')}。出片后我把结果发过来。"}

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
                                  str(params.get("query") or ""),
                                  str(params.get("asset_id") or ""))
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
            float(params["megapixels"]) if params.get("megapixels") else None,
            str(params.get("audio_asset_id") or ""),
            [str(x) for x in (params.get("audio_asset_ids") or [])])
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
                                  {"params": params, "status": "queued",
                                   "parent_ref": params.get("parent_ref"),
                                   "note": params.get("note", "")})
    _emit({"t": "artifact", "kind": kind, "ref_id": data["job_id"],
                   "artifact_id": artifact["id"], "url": ""})
    what = "视频" if is_video else "图"
    return {"reply": f"已提交，任务 id {data['job_id']}。{what}出来后我会把结果发过来。"}


def route_after_decide(state: AgentState) -> str:
    intent = state.get("intent") or "chat"
    if intent == "audit":
        return "audit"
    if intent == "list_shots":
        return "list_shots"
    if intent == "lookup":
        return "lookup"
    if intent == "advise":
        return "advise"
    if intent == "explain":
        return "explain"
    if intent == "chat" and str(state.get("reply") or "").strip():
        return "quick_reply"
    if intent in {"capability", "list_presets"}:
        return "reply_capability"
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
    if intent == "multi":
        return "prepare_multi"
    if intent == "revise":
        return "prepare_revise"
    if intent == "create_project":
        return "prepare_new_project"
    if intent == "add_shot":
        return "prepare_add_shot"
    return "chat"


def route_after_prepare(state: AgentState) -> str:
    # 计划已在上一轮确认过 → 跳过确认门，直接执行
    if state.get("preapproved") and state.get("intent") == "multi":
        return "dispatch_multi"
    if state.get("intent") == "chat":
        # 节点里已经写好了提示（比如「没听出要改什么」），直接回，不用再等模型
        return "quick_reply" if str(state.get("reply") or "").strip() else "chat"
    return "confirm"


def route_after_confirm(state: AgentState) -> str:
    if state.get("decision") != "approved":
        # 取消就是取消：用本地写好的回复，别让模型再发挥
        return "quick_reply" if str(state.get("reply") or "").strip() else "chat"
    kind = (state.get("plan") or {}).get("kind")
    return "dispatch_multi" if kind == "multi" else "dispatch"


def build_graph(checkpointer=None):
    """checkpointer 由 runtime 注入（持久化到 SQLite）；不传则退化为内存版。"""
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()

    graph = StateGraph(AgentState)
    graph.add_node("intake", node_intake)
    graph.add_node("decide", node_decide)
    graph.add_node("chat", node_chat)
    graph.add_node("reply_capability", node_reply_capability)
    graph.add_node("quick_reply", node_quick_reply)
    graph.add_node("explain", node_explain)
    graph.add_node("advise", node_advise)
    graph.add_node("lookup", node_lookup)
    graph.add_node("list_shots", node_list_shots)
    graph.add_node("audit", node_audit)
    graph.add_node("prepare", node_prepare)
    graph.add_node("prepare_export", node_prepare_export)
    graph.add_node("prepare_save", node_prepare_save)
    graph.add_node("prepare_polish", node_prepare_polish)
    graph.add_node("prepare_bgm", node_prepare_bgm)
    graph.add_node("prepare_film", node_prepare_film)
    graph.add_node("prepare_new_project", node_prepare_new_project)
    graph.add_node("prepare_revise", node_prepare_revise)
    graph.add_node("prepare_multi", node_prepare_multi)
    graph.add_node("dispatch_multi", node_dispatch_multi)
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
                                 "prepare_add_shot": "prepare_add_shot",
                                 "reply_capability": "reply_capability",
                                 "explain": "explain",
                                 "advise": "advise",
                                 "list_shots": "list_shots",
                                 "audit": "audit",
                                 "prepare_revise": "prepare_revise",
                                 "prepare_multi": "prepare_multi",
                                 "quick_reply": "quick_reply"})
    graph.add_edge("lookup", END)
    graph.add_edge("list_shots", END)
    graph.add_edge("audit", END)
    graph.add_conditional_edges("prepare", route_after_prepare,
                                {"chat": "chat", "confirm": "confirm",
                                 "quick_reply": "quick_reply"})
    graph.add_conditional_edges("prepare_multi", route_after_prepare,
                                {"confirm": "confirm", "chat": "chat",
                                 "quick_reply": "quick_reply",
                                 "dispatch_multi": "dispatch_multi"})
    for name in ("prepare_export", "prepare_save", "prepare_polish", "prepare_bgm",
                 "prepare_film", "prepare_new_project", "prepare_revise", "prepare_add_shot"):
        graph.add_conditional_edges(name, route_after_prepare,
                                    {"confirm": "confirm", "chat": "chat",
                                     "quick_reply": "quick_reply"})
    graph.add_conditional_edges("confirm", route_after_confirm,
                                {"dispatch": "dispatch", "chat": "chat",
                                 "dispatch_multi": "dispatch_multi",
                                 "quick_reply": "quick_reply"})
    graph.add_edge("dispatch", END)
    graph.add_edge("dispatch_multi", END)
    graph.add_edge("chat", END)
    graph.add_edge("reply_capability", END)
    graph.add_edge("explain", END)
    graph.add_edge("advise", END)
    graph.add_edge("quick_reply", END)
    return graph.compile(checkpointer=checkpointer)

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
import time

import httpx
from langchain_core.tools import tool

from . import planner, state as agent_state, store as agent_store, tools
from .. import store
from ..config import settings

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

## 你能查到的信息（先查再答，不要说不了解）
- `studio_overview()`：整个工作台的总量——几个项目、多少镜头、素材各多少、导出过几次
- `list_projects()`：所有项目清单（名称、镜头数、创建时间、最近一次导出）
- `project_stats(project_id)`：单个项目的细节（镜头数、几个已有画面、总时长、导出次数）
- `comfy_status()`：ComfyUI 现在通不通、地址、队列里在跑几个、排了几个
- `list_shots` / `find_assets` / `describe_state` / `card_info`：镜头、素材、本会话产物、能力卡参数

用户问「ComfyUI 通吗」「我做过多少项目」「这个项目多少镜头」这类问题，
必须先用上面的工具查，再据此回答；查不到就明说查不到，不要凭空推测。

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
9. 回复用 markdown 排版：要点用列表、清单/对比用表格、参数用 `行内代码`。

## 当前上下文
{state}
"""


_STATUS_CACHE: dict = {"at": 0.0, "data": {}}


def _comfy_status(fresh: bool = False) -> dict:
    """2 秒超时探一次 ComfyUI；30 秒内复用结果。"""
    now = time.time()
    if not fresh and now - _STATUS_CACHE["at"] < 30 and _STATUS_CACHE["data"]:
        return _STATUS_CACHE["data"]
    # 库里的覆盖值优先（服务未走 lifespan 时 settings 还是 config.yaml 的默认值）
    try:
        stored = store.list_settings()
    except Exception:  # noqa: BLE001
        stored = {}
    base = str(stored.get("comfy.base_url") or settings.base_url or "").rstrip("/")
    mode = stored.get("comfy.mode") or settings.comfy_mode
    data: dict = {"base_url": base, "mode": mode, "ok": False}
    if base:
        started = time.time()
        try:
            with httpx.Client(trust_env=False, timeout=2.0) as client:
                resp = client.get(base + "/queue")
                ok = resp.status_code < 400
                data["ok"] = ok
                data["latency_ms"] = int((time.time() - started) * 1000)
                if ok:
                    payload = resp.json() or {}
                    data["running"] = len(payload.get("queue_running") or [])
                    data["pending"] = len(payload.get("queue_pending") or [])
        except Exception as exc:  # noqa: BLE001
            data["error"] = f"{type(exc).__name__}"
    _STATUS_CACHE.update({"at": now, "data": data})
    return data


def _library_counts() -> dict:
    counts = {}
    total = 0
    for kind in ("image", "video", "audio"):
        try:
            _, n = store.search_assets(kind, "", 1, 0)
            counts[kind] = n
            total += n
        except Exception:  # noqa: BLE001
            counts[kind] = 0
    counts["total"] = total
    return counts


def _world_text(project_id: str) -> list[str]:
    lines: list[str] = []
    try:
        projects = store.list_projects()
    except Exception:  # noqa: BLE001
        projects = []
    counts = _library_counts()
    status = _comfy_status()

    lines.append(f"- 工作台总量：项目 {len(projects)} 个 · 素材 {counts['total']} 个"
                 f"（图 {counts.get('image', 0)} / 视频 {counts.get('video', 0)} / 音频 {counts.get('audio', 0)}）")
    if projects:
        preview = []
        for item in projects[:6]:
            try:
                shots = len(store.list_shots(item["id"]))
            except Exception:  # noqa: BLE001
                shots = 0
            preview.append(f"{item.get('name') or '未命名'}（{shots} 镜）")
        lines.append("- 项目清单（前 6 个）：" + "；".join(preview))

    state = "在线" if status.get("ok") else "连不上"
    extra = ""
    if status.get("ok"):
        extra = f"，队列 跑 {status.get('running', 0)} / 排 {status.get('pending', 0)}"
    elif status.get("error"):
        extra = f"（{status['error']}）"
    lines.append(f"- ComfyUI：{state} · {status.get('base_url') or '未配置'}"
                 f" · 模式 {status.get('mode')}{extra}")

    if project_id:
        try:
            shots = store.list_shots(project_id)
            renders = store.list_renders(project_id, 5)
        except Exception:  # noqa: BLE001
            shots, renders = [], []
        with_cover = sum(1 for s in shots if s.get("cover"))
        with_video = sum(1 for s in shots if s.get("active_job"))
        lines.append(f"- 当前项目镜头 {len(shots)} 个（有首帧/封面 {with_cover} 个，"
                     f"已出视频 {with_video} 个）· 导出记录 {len(renders)} 条")
    return lines


def _state_text(thread_id: str, project_id: str, attachments: list[dict]) -> str:
    st = agent_state.thread_state(thread_id)
    project = store.get_project(project_id) if project_id else None
    name = (project or {}).get("name") or "未命名"
    lines = [f"- 当前项目：《{name}》（{project_id or '未绑定'}）",
             f"- 会话产物：{st['count']} 个"]
    lines.extend(_world_text(project_id))
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
        video_map = {s["id"]: bool(s.get("active_job")) for s in store.list_shots(project_id)}
        lines.append(f"- 项目镜头：{len(shots)} 个")
        for shot in shots[:12]:
            if video_map.get(shot.get("shot_id")):
                state_note = "已出视频"
            elif shot.get("cover"):
                state_note = "只有首帧"
            else:
                state_note = "空镜头"
            lines.append(f"    {shot['ref']} {shot['title']}（{state_note}）")
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
        rows = []
        for s in shots:
            shot = store.get_shot(s.get("id") or "") or {}
            rows.append({"ref": s["ref"], "title": s["title"],
                         "has_cover": bool(s.get("cover")),
                         "has_video": bool(shot.get("active_job"))})
        return json.dumps(rows, ensure_ascii=False)

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

    @tool
    def studio_overview() -> str:
        """整个工作台的总量：项目数、素材数（分类型）、导出记录数、ComfyUI 状态。"""
        log.append({"tool": "studio_overview", "kind": "read", "args": {}})
        projects = store.list_projects()
        shots_total = 0
        for item in projects:
            try:
                shots_total += len(store.list_shots(item["id"]))
            except Exception:  # noqa: BLE001
                continue
        return json.dumps({
            "projects": len(projects),
            "shots": shots_total,
            "assets": _library_counts(),
            "comfy": _comfy_status(fresh=True),
        }, ensure_ascii=False)

    @tool
    def list_projects() -> str:
        """列出所有项目：名称、镜头数、创建时间、最近一次导出状态。"""
        log.append({"tool": "list_projects", "kind": "read", "args": {}})
        out = []
        for item in store.list_projects()[:30]:
            try:
                shots = len(store.list_shots(item["id"]))
            except Exception:  # noqa: BLE001
                shots = 0
            renders = []
            try:
                renders = store.list_renders(item["id"], 1)
            except Exception:  # noqa: BLE001
                pass
            out.append({
                "id": item["id"],
                "name": item.get("name"),
                "shots": shots,
                "created_at": item.get("created_at"),
                "last_render": (renders[0].get("status") if renders else None),
            })
        return json.dumps(out, ensure_ascii=False)

    @tool
    def project_stats(project_id: str = "") -> str:
        """单个项目的细节：镜头数、几个已有画面、总时长、导出次数。project_id 留空=当前项目。"""
        log.append({"tool": "project_stats", "kind": "read", "args": {"project_id": project_id}})
        pid = project_id or ""
        if not pid:
            return json.dumps({"error": "没有指定项目"}, ensure_ascii=False)
        project = store.get_project(pid)
        if not project:
            return json.dumps({"error": "项目不存在"}, ensure_ascii=False)
        shots = store.list_shots(pid)
        with_cover = sum(1 for s in shots if s.get("cover"))
        with_video = sum(1 for s in shots if s.get("active_job"))
        duration = 0.0
        for shot in shots:
            values = shot.get("values") or {}
            try:
                duration += float(values.get("duration") or 0)
            except (TypeError, ValueError):
                continue
        renders = store.list_renders(pid, 5)
        return json.dumps({
            "id": pid, "name": project.get("name"),
            "shots": len(shots), "shots_with_cover": with_cover,
            "shots_with_video": with_video,
            "duration_seconds": round(duration, 1),
            "renders": len(renders),
            "last_render": (renders[0].get("status") if renders else None),
        }, ensure_ascii=False)

    @tool
    def comfy_status() -> str:
        """ComfyUI 现在通不通、地址、队列里跑几个排几个。"""
        log.append({"tool": "comfy_status", "kind": "read", "args": {}})
        return json.dumps(_comfy_status(fresh=True), ensure_ascii=False)

    return [describe_state, list_shots, find_assets, card_info,
            studio_overview, list_projects, project_stats, comfy_status]


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

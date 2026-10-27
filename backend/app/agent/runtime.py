"""把图跑起来：消息落库、事件推送、确认续跑、任务完成回写。"""
from __future__ import annotations

import asyncio
import json
import time

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from .. import store
from . import store as agent_store
from .events import bus
from .checkpoint import ensure_graph

PROCESS_START = time.time()
_tasks: dict[str, asyncio.Task] = {}





def _sink(thread_id: str):
    def emit(event: dict) -> None:
        bus.publish(thread_id, event)
    return emit


def _interrupt_payload(result: dict) -> dict | None:
    """LangGraph 中断时，结果里会带 __interrupt__。"""
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if not interrupts:
        return None
    first = interrupts[0]
    value = getattr(first, "value", None)
    if isinstance(value, dict):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return {"title": "需要确认", "summary": str(value)[:200]}


def _latest_artifact(thread_id: str, run_id: str) -> dict | None:
    for artifact in agent_store.list_artifacts(thread_id, limit=20):
        if artifact["run_id"] == run_id:
            return artifact
    return None


def _watch_artifact(thread_id: str, run_id: str) -> None:
    artifact = _latest_artifact(thread_id, run_id)
    if not artifact:
        return
    if artifact["kind"] == "render":
        asyncio.create_task(watch_render(artifact["ref_id"], run_id, thread_id))
    elif artifact["kind"] == "ai_edit":
        from .. import ai_edit as ai_edit_module

        asyncio.create_task(watch_ai_edit(artifact["ref_id"], run_id, thread_id))
    elif artifact["ref_id"].startswith("job_"):
        asyncio.create_task(watch_job(artifact["ref_id"], run_id, thread_id))


async def start_run(thread: dict, text: str, attachments: list[dict] | None = None) -> dict:
    """新建一轮：写入用户消息，后台跑图，返回 run。"""
    thread_id = thread["id"]
    attachments = attachments or []
    run = agent_store.create_run(thread_id)
    parts = []
    for att in attachments:
        kind = str(att.get("kind") or "")
        if kind not in ("image", "audio", "video"):
            continue
        parts.append({"type": kind, "url": att.get("url") or "",
                      "asset_id": att.get("id") or "",
                      "name": str(att.get("path") or "").rsplit("/", 1)[-1]})
    agent_store.add_message(thread_id, "user", text, parts)

    # 首条消息先给个占位名，随后让模型起个更贴切的（不阻塞回复）
    first_message = thread.get("title") in ("", "新对话")
    if first_message:
        placeholder = text.strip().replace("\n", " ")[:16] or "新对话"
        agent_store.update_thread(thread_id, title=placeholder)
        bus.publish(thread_id, {"t": "thread_title", "title": placeholder})
        asyncio.create_task(_auto_title(thread_id, text))
    bus.publish(thread_id, {"t": "run_start", "run_id": run["id"]})
    task = asyncio.create_task(_run(thread, run["id"], text, attachments))
    _tasks[run["id"]] = task
    task.add_done_callback(lambda _t, rid=run["id"]: _tasks.pop(rid, None))
    return run


async def _run(thread: dict, run_id: str, text: str,
               attachments: list[dict] | None = None,
               steps: list[dict] | None = None) -> None:
    thread_id = thread["id"]
    config = {"configurable": {"thread_id": run_id, "emit": _sink(thread_id)}}
    state = {
        "thread_id": thread_id,
        "project_id": thread.get("project_id", ""),
        "run_id": run_id,
        "text": text,
        "attachments": attachments or [],
        "messages": [HumanMessage(content=text)],
    }
    if steps:
        state["preapproved"] = True
        state["args"] = {"steps": steps}
    try:
        g = await ensure_graph()
        result = await g.ainvoke(state, config)
    except Exception as exc:
        _fail(thread_id, run_id, exc)
        return

    payload = _interrupt_payload(result)
    if payload:
        agent_store.update_run(run_id, status="waiting_confirm", node="confirm",
                               pending_json=payload)
        bus.publish(thread_id, {"t": "need_confirm", "run_id": run_id, **payload})
        return

    _finish(thread_id, run_id, result)

    # 本步没有产物（配乐/片头这类），但还有后续步骤时继续往下推
    try:
        pending = agent_store.get_context(thread_id).get("pending_steps") or []
        produced = [a for a in agent_store.list_artifacts(thread_id, limit=10)
                    if a.get("run_id") == run_id]
        if pending and not produced:
            asyncio.create_task(_resume_pending_steps(thread_id))
    except Exception:
        pass


async def confirm_run(run_id: str, approved: bool, params: dict | None = None) -> dict:
    """用户在确认卡上点了执行/取消。"""
    run = agent_store.get_run(run_id)
    if not run:
        raise ValueError("run 不存在")
    if run["status"] in ("canceled", "failed", "interrupted"):
        raise ValueError("这个确认已经失效，重新发一次消息就好")
    thread_id = run["thread_id"]
    config = {"configurable": {"thread_id": run_id, "emit": _sink(thread_id)}}
    payload: dict = {"approved": approved}
    if params:
        payload["params"] = params
    try:
        g = await ensure_graph()
        result = await g.ainvoke(Command(resume=payload), config)
    except Exception as exc:
        text = str(exc)
        # 没有 checkpoint（老数据 / 被清理）时，明确告诉用户重发
        if "checkpoint" in text.lower() or "resume" in text.lower() or "thread" in text.lower():
            agent_store.update_run(run_id, status="interrupted", error="确认上下文已丢失")
            raise ValueError("这个确认已经失效（找不到当时的上下文），重新发一次消息就好")
        _fail(thread_id, run_id, exc)
        raise

    _finish(thread_id, run_id, result)

    if approved:
        _watch_artifact(thread_id, run_id)
    return agent_store.get_run(run_id) or {}


def _fail(thread_id: str, run_id: str, exc: Exception) -> None:
    message = f"出错了：{str(exc)[:200]}"
    agent_store.update_run(run_id, status="failed", error=str(exc)[:500],
                           finished_at=time.time())
    # 失败也要在对话里留一条，用户才知道发生了什么
    try:
        agent_store.add_message(thread_id, "assistant", message,
                                [{"type": "error", "text": str(exc)[:400]}], run_id)
    except Exception:
        pass
    bus.publish(thread_id, {"t": "message", "role": "assistant", "content": message,
                            "parts": [{"type": "error", "text": str(exc)[:400]}]})
    bus.publish(thread_id, {"t": "run_end", "run_id": run_id, "status": "failed",
                            "error": str(exc)[:300]})


def _finish(thread_id: str, run_id: str, result: dict) -> None:
    reply = str(result.get("reply") or "").strip()
    if reply:
        _append_assistant(thread_id, run_id, reply, result)
    agent_store.update_run(run_id, status="done", node="", finished_at=time.time(),
                           state_json={"intent": result.get("intent"),
                                       "plan": result.get("plan")})
    bus.publish(thread_id, {"t": "run_end", "run_id": run_id, "status": "done"})


def _append_assistant(thread_id: str, run_id: str, reply: str, result: dict) -> dict:
    parts: list[dict] = []
    assets = (result.get("args") or {}).get("assets")
    if isinstance(assets, list) and assets:
        parts.append({"type": "assets", "items": assets})
    msg = agent_store.add_message(thread_id, "assistant", reply, parts, run_id)
    # 流式已经逐字推过了，这里只发一个 final 标记，避免前端重复一遍
    event = {"t": "message", "role": "assistant", "content": reply,
             "parts": parts, "message_id": msg["id"]}
    if result.get("streamed"):
        event["final"] = True
    bus.publish(thread_id, event)
    return msg


async def watch_job(job_id: str, run_id: str, thread_id: str,
                    interval: float = 3.0, timeout: float = 2400.0) -> None:
    """任务完成/失败后，把结果作为一条新消息追加。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(interval)
        job = store.get_job(job_id)
        if not job:
            return
        status = job.get("status")
        if status not in {"succeeded", "failed", "canceled"}:
            continue
        outputs = job.get("outputs") or []
        url = ""
        kind = "image"
        if outputs and isinstance(outputs[0], dict):
            url = str(outputs[0].get("url") or "")
            out_kind = str(outputs[0].get("kind") or "")
            if out_kind in {"video", "image", "audio"}:
                kind = out_kind
        if url.lower().endswith((".mp4", ".webm", ".mov")):
            kind = "video"
        existing = agent_store.find_artifact(thread_id, job_id)
        meta = {"status": status, "error": job.get("error", "")}
        if existing:
            artifact = agent_store.update_artifact(
                existing["id"], url=url, kind=kind,
                meta={**(existing.get("meta") or {}), **meta}) or existing
        else:
            artifact = agent_store.add_artifact(run_id, thread_id, kind, job_id, url, meta)
        if status == "succeeded":
            _remember_output(thread_id, job, kind, url)
            try:
                await _resume_pending_steps(thread_id)
            except Exception:
                pass
        text = ("视频出来了" if kind == "video" else "图出来了") \
            if status == "succeeded" else f"生成失败：{job.get('error') or status}"
        parts = [{"type": kind, "url": url, "job_id": job_id,
                  "artifact_id": artifact["id"], "status": status}]
        agent_store.add_message(thread_id, "assistant", text, parts, run_id)
        bus.publish(thread_id, {"t": "artifact", "kind": kind, "ref_id": job_id,
                                "artifact_id": artifact["id"], "url": url,
                                "status": status})
        bus.publish(thread_id, {"t": "message", "role": "assistant", "content": text,
                                "parts": parts})
        return


async def watch_render(render_id: str, run_id: str, thread_id: str,
                       interval: float = 3.0, timeout: float = 3600.0) -> None:
    """成片导出完成后把结果作为新消息追加。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(interval)
        render = store.get_render(render_id)
        if not render:
            return
        status = render.get("status")
        if status not in {"succeeded", "failed", "canceled"}:
            continue
        url = f"/media/files/renders/{render_id}/final.mp4" if status == "succeeded" else ""
        existing = agent_store.find_artifact(thread_id, render_id)
        meta = {"status": status, "error": render.get("error", ""), "source": "render"}
        if existing:
            artifact = agent_store.update_artifact(
                existing["id"], url=url, kind="video",
                meta={**(existing.get("meta") or {}), **meta}) or existing
        else:
            artifact = agent_store.add_artifact(run_id, thread_id, "video", render_id, url, meta)
        text = "成片出来了" if status == "succeeded" else f"导出失败：{render.get('error') or status}"
        parts = [{"type": "video", "url": url, "render_id": render_id,
                  "artifact_id": artifact["id"], "status": status}]
        agent_store.add_message(thread_id, "assistant", text, parts, run_id)
        bus.publish(thread_id, {"t": "artifact", "kind": "video", "ref_id": render_id,
                                "artifact_id": artifact["id"], "url": url, "status": status})
        bus.publish(thread_id, {"t": "message", "role": "assistant", "content": text,
                                "parts": parts})
        return


async def _auto_title(thread_id: str, text: str) -> None:
    """让模型给会话起个短标题，失败就保留占位名。"""
    from .. import ai_script

    try:
        title = await ai_script.thread_title(text)
    except Exception:
        return
    title = (title or "").strip()
    if not title:
        return
    agent_store.update_thread(thread_id, title=title)
    bus.publish(thread_id, {"t": "thread_title", "title": title})


def _remember_output(thread_id: str, job: dict, kind: str, url: str) -> None:
    """记住刚生成的东西，下一轮「用这张图」才接得上。"""
    patch = {
        "last_kind": kind,
        "last_job_id": job.get("id", ""),
        "last_url": url,
        "last_prompt": (job.get("inputs") or {}).get("prompt", ""),
        "last_preset": job.get("preset_id", ""),
    }
    if kind == "image" and url:
        from . import tools as tools_module

        asset_id = tools_module.asset_from_url(url, job.get("id", ""))
        if asset_id:
            patch["last_asset_id"] = asset_id
    agent_store.set_context(thread_id, patch)


def _rel_from_url(url: str) -> str:
    """把 /media/xxx/yyy 转成相对 data 的路径：outputs/xxx、uploads/yyy、files 直接取余下部分。

    之前用 split("/media/files/") 处理所有 URL，遇到 /media/outputs/... 会把整串当路径，
    结果素材路径变成 "/media/outputs/..."，后续读文件就落到 D:\media\... 上。
    """
    url = (url or "").strip()
    for prefix, root in (("/media/files/", ""), ("/media/outputs/", "outputs/"),
                         ("/media/uploads/", "uploads/")):
        if url.startswith(prefix):
            rest = url[len(prefix):]
            return f"{root}{rest}" if root else rest
    return ""


async def mark_stale_runs() -> int:
    """服务启动时，把上次进程留下的 running / waiting_confirm 标成 interrupted。"""
    from .store import connect

    with connect() as conn:
        # waiting_confirm 的 checkpoint 已落库，重启后仍可点确认；只把真正在跑的标中断
        cur = conn.execute(
            "UPDATE agent_runs SET status='interrupted', error='服务重启导致中断',"
            " finished_at=? WHERE status='running'", (time.time(),))
        return cur.rowcount


async def cancel_run(run_id: str, reason: str = "用户取消") -> dict:
    """取消一个运行：停掉后台 task，把状态置 canceled。"""
    run = agent_store.get_run(run_id)
    if not run:
        raise ValueError("run 不存在")
    if run["status"] in ("done", "failed", "canceled"):
        return run

    task = _tasks.pop(run_id, None)
    if task and not task.done():
        task.cancel()

    thread_id = run["thread_id"]
    agent_store.update_run(run_id, status="canceled", error=reason, finished_at=time.time())
    agent_store.add_message(thread_id, "assistant", f"已取消（{reason}）",
                            [{"type": "notice", "text": reason}], run_id)
    bus.publish(thread_id, {"t": "run_end", "run_id": run_id, "status": "canceled"})
    return agent_store.get_run(run_id) or {}


async def watch_ai_edit(edit_run_id: str, run_id: str, thread_id: str,
                        interval: float = 4.0, timeout: float = 3600.0) -> None:
    """AI 剪辑跑完后把结果写回对话，并把逐镜进度转发成 step 事件。"""
    from .. import ai_edit as ai_edit_module

    deadline = time.time() + timeout
    seen_rows: set[str] = set()
    while time.time() < deadline:
        run = ai_edit_module.get_run(edit_run_id)
        if not run:
            return
        for sid, row in (run.get("state") or {}).get("rows", {}).items():
            if sid in seen_rows:
                continue
            seen_rows.add(sid)
            bus.publish(thread_id, {"t": "step", "id": f"aied_{sid}",
                                    "node": "ai_edit", "title": row.get("title", ""),
                                    "status": "done" if row.get("status") == "done" else "error",
                                    "detail": {"note": row.get("note", "")}})
        if run["status"] in ("done", "failed", "canceled"):
            state = run.get("state") or {}
            done = state.get("done", 0)
            total = state.get("total", 0)
            if run["status"] == "done":
                text = f"AI 剪辑完成：{done}/{total} 镜（字幕/旁白/配音已写入项目）"
            elif run["status"] == "canceled":
                text = "AI 剪辑已取消"
            else:
                text = f"AI 剪辑失败：{run.get('error') or ''}"
            agent_store.add_message(thread_id, "assistant", text,
                                    [{"type": "notice", "text": text}], run_id)
            bus.publish(thread_id, {"t": "message", "role": "assistant",
                                    "content": text, "parts": [{"type": "notice", "text": text}]})
            return
        await asyncio.sleep(interval)


async def _resume_pending_steps(thread_id: str) -> None:
    """产物的依赖步骤：等上一步出结果后继续跑剩下的计划。"""
    ctx = agent_store.get_context(thread_id)
    steps = list(ctx.get("pending_steps") or [])
    if not steps:
        return
    latest = ctx.get("last_asset_id")
    first = dict(steps[0])
    args = dict(first.get("args") or {})
    if first.get("intent") == "generate_video" and args.get("mode") == "i2v" and latest:
        args["image_asset_id"] = latest
    first["args"] = args
    # 只跑下一步；剩下的等这一步的产物出来再续（支持三级/四级依赖）
    rest = steps[1:]
    agent_store.set_context(thread_id, {"pending_steps": rest})

    thread = agent_store.get_thread(thread_id)
    if not thread:
        return
    run = agent_store.create_run(thread_id)
    agent_store.add_message(thread_id, "assistant",
                            "上一步产物出来了，我接着做剩下的步骤。",
                            [{"type": "notice", "text": "继续执行计划"}], run["id"])
    bus.publish(thread_id, {"t": "run_start", "run_id": run["id"]})
    # 只执行这一步；rest 留在上下文里，等这一步的产物出来再续
    task = asyncio.create_task(_run(thread, run["id"], "继续执行剩余步骤", None, [first]))
    _tasks[run["id"]] = task
    task.add_done_callback(lambda _t, rid=run["id"]: _tasks.pop(rid, None))

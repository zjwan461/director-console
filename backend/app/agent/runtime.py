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
from .graph import build_graph

_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


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
    elif artifact["ref_id"].startswith("job_"):
        asyncio.create_task(watch_job(artifact["ref_id"], run_id, thread_id))


async def start_run(thread: dict, text: str, attachments: list[dict] | None = None) -> dict:
    """新建一轮：写入用户消息，后台跑图，返回 run。"""
    thread_id = thread["id"]
    attachments = attachments or []
    run = agent_store.create_run(thread_id)
    parts = [{"type": "image", "url": a["url"], "asset_id": a["id"], "name": a["path"].rsplit("/", 1)[-1]}
             for a in attachments if a.get("kind") == "image"]
    agent_store.add_message(thread_id, "user", text, parts)

    # 首条消息先给个占位名，随后让模型起个更贴切的（不阻塞回复）
    first_message = thread.get("title") in ("", "新对话")
    if first_message:
        placeholder = text.strip().replace("\n", " ")[:16] or "新对话"
        agent_store.update_thread(thread_id, title=placeholder)
        bus.publish(thread_id, {"t": "thread_title", "title": placeholder})
        asyncio.create_task(_auto_title(thread_id, text))
    bus.publish(thread_id, {"t": "run_start", "run_id": run["id"]})
    asyncio.create_task(_run(thread, run["id"], text, attachments))
    return run


async def _run(thread: dict, run_id: str, text: str,
               attachments: list[dict] | None = None) -> None:
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
    try:
        result = await graph().ainvoke(state, config)
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


async def confirm_run(run_id: str, approved: bool, params: dict | None = None) -> dict:
    """用户在确认卡上点了执行/取消。"""
    run = agent_store.get_run(run_id)
    if not run:
        raise ValueError("run 不存在")
    thread_id = run["thread_id"]
    config = {"configurable": {"thread_id": run_id, "emit": _sink(thread_id)}}
    payload: dict = {"approved": approved}
    if params:
        payload["params"] = params
    try:
        result = await graph().ainvoke(Command(resume=payload), config)
    except Exception as exc:
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
        try:
            rel = url.split("/media/files/", 1)[-1]
            asset = store.get_asset_by_path(rel) or store.add_asset(
                "image", rel, meta={"origin": "agent", "job_id": job.get("id", "")})
            if asset:
                patch["last_asset_id"] = asset["id"]
        except Exception:
            pass
    agent_store.set_context(thread_id, patch)

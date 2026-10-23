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


def _job_id_of_run(thread_id: str, run_id: str) -> str:
    for artifact in agent_store.list_artifacts(thread_id, limit=20):
        if artifact["run_id"] == run_id and artifact["ref_id"].startswith("job_"):
            return artifact["ref_id"]
    return ""


async def start_run(thread: dict, text: str) -> dict:
    """新建一轮：写入用户消息，后台跑图，返回 run。"""
    thread_id = thread["id"]
    run = agent_store.create_run(thread_id)
    agent_store.add_message(thread_id, "user", text)
    bus.publish(thread_id, {"t": "run_start", "run_id": run["id"]})
    asyncio.create_task(_run(thread, run["id"], text))
    return run


async def _run(thread: dict, run_id: str, text: str) -> None:
    thread_id = thread["id"]
    config = {"configurable": {"thread_id": run_id, "emit": _sink(thread_id)}}
    state = {
        "thread_id": thread_id,
        "project_id": thread.get("project_id", ""),
        "run_id": run_id,
        "text": text,
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

    job_id = _job_id_of_run(thread_id, run_id)
    if approved and job_id:
        asyncio.create_task(watch_job(job_id, run_id, thread_id))
    return agent_store.get_run(run_id) or {}


def _fail(thread_id: str, run_id: str, exc: Exception) -> None:
    agent_store.update_run(run_id, status="failed", error=str(exc)[:500],
                           finished_at=time.time())
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
    bus.publish(thread_id, {"t": "message", "role": "assistant", "content": reply,
                            "parts": parts, "message_id": msg["id"]})
    return msg


async def watch_job(job_id: str, run_id: str, thread_id: str,
                    interval: float = 2.0, timeout: float = 900.0) -> None:
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
        if outputs and isinstance(outputs[0], dict):
            url = str(outputs[0].get("url") or "")
        artifact = agent_store.add_artifact(
            run_id, thread_id, "image", job_id, url,
            {"status": status, "error": job.get("error", "")})
        text = "图出来了" if status == "succeeded" else f"生成失败：{job.get('error') or status}"
        parts = [{"type": "image", "url": url, "job_id": job_id,
                  "artifact_id": artifact["id"], "status": status}]
        agent_store.add_message(thread_id, "assistant", text, parts, run_id)
        bus.publish(thread_id, {"t": "artifact", "kind": "image", "ref_id": job_id,
                                "artifact_id": artifact["id"], "url": url,
                                "status": status})
        bus.publish(thread_id, {"t": "message", "role": "assistant", "content": text,
                                "parts": parts})
        return

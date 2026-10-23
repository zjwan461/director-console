"""导演助手 REST + SSE。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import store
from . import runtime
from .events import bus
from . import store as agent_store

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ThreadCreate(BaseModel):
    project_id: str
    title: str = "新对话"


class ThreadPatch(BaseModel):
    title: str | None = None
    archived: bool | None = None


class MessageIn(BaseModel):
    text: str
    attachments: list[str] = []


class ConfirmIn(BaseModel):
    approved: bool = True
    params: dict | None = None


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
@router.get("/threads")
async def list_threads(project_id: str | None = None, limit: int = 30) -> dict:
    return {"items": agent_store.list_threads(project_id, limit)}


@router.post("/threads")
async def create_thread(body: ThreadCreate) -> dict:
    if not body.project_id:
        raise HTTPException(status_code=400, detail="必须绑定一个项目")
    if not store.get_project(body.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return agent_store.create_thread(body.project_id, body.title or "新对话")


@router.patch("/threads/{thread_id}")
async def patch_thread(thread_id: str, body: ThreadPatch) -> dict:
    thread = agent_store.update_thread(
        thread_id, title=body.title,
        archived=None if body.archived is None else int(body.archived))
    if not thread:
        raise HTTPException(status_code=404, detail="会话不存在")
    return thread


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str) -> dict:
    agent_store.delete_thread(thread_id)
    return {"ok": True}


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str) -> dict:
    thread = agent_store.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="会话不存在")
    project = store.get_project(thread["project_id"]) or {}
    return {"thread": thread, "project": {"id": project.get("id"), "name": project.get("name")},
            "runs": agent_store.list_active_runs(thread_id),
            "artifacts": agent_store.list_artifacts(thread_id, limit=12)}


# --------------------------------------------------------------------------- #
# 消息
# --------------------------------------------------------------------------- #
@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, after_seq: int = Query(0, ge=0), limit: int = 200) -> dict:
    return {"items": agent_store.list_messages(thread_id, after_seq, limit)}


@router.post("/threads/{thread_id}/messages")
async def post_message(thread_id: str, body: MessageIn) -> dict:
    thread = agent_store.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="会话不存在")
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")
    run = await runtime.start_run(thread, text)
    return {"run_id": run["id"], "status": run["status"]}


@router.get("/threads/{thread_id}/stream")
async def stream(thread_id: str, after_seq: int = 0) -> StreamingResponse:
    async def gen():
        queue = bus.subscribe(thread_id)
        try:
            # after_seq=0 视为首次连接：历史由 /messages 恢复，不重放旧事件，
            # 否则刷新后会把上一轮的步骤再播一遍
            if after_seq > 0:
                for event in bus.replay(thread_id, after_seq):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            bus.unsubscribe(thread_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# 运行
# --------------------------------------------------------------------------- #
@router.post("/runs/{run_id}/confirm")
async def confirm(run_id: str, body: ConfirmIn) -> dict:
    try:
        return await runtime.confirm_run(run_id, body.approved, body.params)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = agent_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run 不存在")
    return run

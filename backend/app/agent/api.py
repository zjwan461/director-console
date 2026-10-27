"""导演助手 REST + SSE。"""
from __future__ import annotations

import asyncio
import json
import time

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
    # 早期版本对同一个 job 会插两条（占位 + 完成），这里顺手清一下
    agent_store.dedupe_artifacts(thread_id)
    artifacts = _heal_artifacts(agent_store.list_artifacts(thread_id, limit=12))
    # 给产物编号（只算有 url 的），前端显示 #1 #2，修订时也按这个号指代
    with_url = sorted([a for a in artifacts if a.get("url")],
                      key=lambda a: (float(a.get("created_at") or 0), int(a.get("seq") or 0)))
    ref_of = {a["id"]: index for index, a in enumerate(with_url, start=1)}
    for item in artifacts:
        item["ref"] = ref_of.get(item["id"], 0)
        item["parent_ref"] = (item.get("meta") or {}).get("parent_ref")
        item["note"] = (item.get("meta") or {}).get("note") or ""
    return {"thread": thread, "project": {"id": project.get("id"), "name": project.get("name")},
            "runs": agent_store.list_active_runs(thread_id),
            "artifacts": artifacts}


def _heal_artifacts(items: list[dict]) -> list[dict]:
    """占位产物：去查真实任务/成片状态，完成或失败就地更新，别一直挂「排队中」。"""
    healed: list[dict] = []
    for item in items:
        status = str((item.get("meta") or {}).get("status") or "")
        if item.get("url") or (status and status not in ("queued", "running")):
            healed.append(item)
            continue

        ref = item.get("ref_id") or ""
        url, final, error = "", "", ""
        if ref.startswith("job_"):
            job = store.get_job(ref)
            if job:
                final = str(job.get("status") or "")
                outputs = job.get("outputs") or []
                if outputs and isinstance(outputs[0], dict):
                    url = str(outputs[0].get("url") or "")
                error = str(job.get("error") or "")
            else:
                final, error = "failed", "任务已不存在"
        elif ref.startswith("rnd_"):
            render = store.get_render(ref)
            if render:
                final = str(render.get("status") or "")
                if final == "succeeded":
                    url = f"/media/files/renders/{ref}/final.mp4"
                error = str(render.get("error") or "")
            else:
                final, error = "failed", "成片记录已不存在"

        if final in ("succeeded", "failed", "canceled"):
            meta = {**(item.get("meta") or {}), "status": final, "error": error}
            item = agent_store.update_artifact(item["id"], url=url or None, meta=meta) or item
        healed.append(item)
    return healed


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: str, after_seq: int = Query(0, ge=0), limit: int = 200) -> dict:
    return {"items": agent_store.list_messages(thread_id, after_seq, limit)}


@router.post("/threads/{thread_id}/messages")
async def post_message(thread_id: str, body: MessageIn) -> dict:
    thread = agent_store.get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="会话不存在")
    text = (body.text or "").strip()
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="消息不能为空")

    # 连点两次「发送」会重复起两轮，这里做一次 5 秒去抖
    recent = agent_store.list_messages(thread_id, 0, 200)
    if recent:
        last = recent[-1]
        if last["role"] == "user" and last["content"].strip() == text \
                and time.time() - float(last["created_at"] or 0) < 5:
            return {"run_id": "", "status": "duplicate"}

    attachments: list[dict] = []
    for asset_id in body.attachments[:4]:
        asset = store.get_asset(asset_id)
        if not asset:
            continue
        attachments.append({
            "id": asset["id"],
            "kind": asset["kind"],
            "path": asset["path"],
            "url": f"/media/files/{asset['path']}",
        })
    run = await runtime.start_run(thread, text, attachments)
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
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str) -> dict:
    try:
        return await runtime.cancel_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = agent_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run 不存在")
    return run

"""AI 剪辑（服务端批量）的 REST + SSE。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import ai_edit
from .agent.events import bus

router = APIRouter(prefix="/api/ai-edit", tags=["ai-edit"])


class StartIn(BaseModel):
    project_id: str
    shot_ids: list[str] = []
    options: dict = {}


@router.post("/runs")
async def start(body: StartIn) -> dict:
    try:
        return await ai_edit.start(body.project_id, body.shot_ids, body.options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs")
async def list_runs(project_id: str | None = None, active: bool = False, limit: int = 20) -> dict:
    return {"items": ai_edit.list_runs(project_id, active, limit)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = ai_edit.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="任务不存在")
    return run


@router.post("/runs/{run_id}/retry")
async def retry(run_id: str) -> dict:
    try:
        return await ai_edit.retry_failed(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}/stream")
async def stream(run_id: str, after_seq: int = 0) -> StreamingResponse:
    async def gen():
        run = ai_edit.get_run(run_id)
        if not run:
            yield f"data: {json.dumps({'t': 'error', 'text': '任务不存在'}, ensure_ascii=False)}\n\n"
            return

        # 先把已经发生的事件补一遍（点开晚了也能看到完整进度）
        for event in bus.replay(run_id, after_seq):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        if run["status"] in ("done", "failed"):
            state = run.get("state") or {}
            summary = {
                "t": "done" if run["status"] == "done" else "error",
                "summary": f"成功 {state.get('done', 0)}/{state.get('total', 0)} 镜",
                "rows": state.get("rows") or {},
            }
            yield f"data: {json.dumps(summary, ensure_ascii=False)}\n\n"
            return

        queue = bus.subscribe(run_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("t") in ("done", "error"):
                    break
        finally:
            bus.unsubscribe(run_id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

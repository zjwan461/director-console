"""统一任务中心：把 jobs / renders / agent runs / ai-edit runs 汇成一个列表。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Query

from . import ai_edit, store
from .agent import store as agent_store

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

ACTIVE = ("queued", "preparing", "uploading", "running", "waiting_confirm", "rendering")


def _job_title(job: dict) -> str:
    shot = store.get_shot(job.get("shot_id") or "") or {}
    if shot.get("title"):
        return shot["title"]
    return (job.get("preset_id") or "生成任务").replace(".", " · ")


def _render_title(render: dict) -> str:
    project = store.get_project(render.get("project_id") or "") or {}
    try:
        count = len(json.loads(render.get("shot_ids") or "[]"))
    except Exception:
        count = 0
    return f"{project.get('name') or '成片'} · {count} 镜"


def collect(limit: int = 40, active_only: bool = False) -> list[dict]:
    items: list[dict] = []

    for job in store.list_jobs(limit=limit)[0]:
        items.append({
            "id": job["id"], "kind": "job", "title": _job_title(job),
            "status": job["status"], "progress": job.get("progress") or 0,
            "message": job.get("message") or "", "error": job.get("error") or "",
            "created_at": job.get("created_at") or 0,
            "project_id": job.get("project_id") or "",
            "cancelable": job["status"] in ACTIVE,
        })

    for render in store.list_renders_all(limit) if hasattr(store, "list_renders_all") else []:
        items.append({
            "id": render["id"], "kind": "render", "title": _render_title(render),
            "status": render["status"], "progress": render.get("progress") or 0,
            "message": render.get("message") or "", "error": render.get("error") or "",
            "created_at": render.get("created_at") or 0,
            "project_id": render.get("project_id") or "",
            "cancelable": render["status"] in ACTIVE,
        })

    for edit_run in ai_edit.list_runs(None, False, limit):
        state = edit_run.get("state") or {}
        items.append({
            "id": edit_run["id"], "kind": "ai_edit", "title": "AI 剪辑",
            "status": edit_run["status"],
            "progress": (state.get("done") or 0) / max(1, state.get("total") or 1),
            "message": f"{state.get('done') or 0}/{state.get('total') or 0} 镜",
            "error": edit_run.get("error") or "",
            "created_at": edit_run.get("created_at") or 0,
            "project_id": edit_run.get("project_id") or "",
            "cancelable": edit_run["status"] in ("running", "queued"),
        })

    for run in agent_store.list_runs(None, limit):
        if run["status"] not in ACTIVE and not run.get("finished_at"):
            continue
        thread = agent_store.get_thread(run["thread_id"]) or {}
        items.append({
            "id": run["id"], "kind": "agent", "title": thread.get("title") or "导演助手",
            "status": run["status"], "progress": 0,
            "message": run.get("node") or "", "error": run.get("error") or "",
            "created_at": run.get("started_at") or 0,
            "project_id": thread.get("project_id") or "",
            "cancelable": run["status"] in ("running", "waiting_confirm"),
        })

    if active_only:
        items = [i for i in items if i["status"] in ACTIVE]
    items.sort(key=lambda i: i["created_at"], reverse=True)
    return items[:limit]


@router.get("")
async def list_tasks(limit: int = Query(40, ge=1, le=200), active_only: bool = False) -> dict:
    items = collect(limit, active_only)
    return {"items": items, "total": len(items),
            "active": sum(1 for i in items if i["status"] in ACTIVE)}

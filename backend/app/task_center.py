"""统一任务中心：把 jobs / renders / agent runs / ai-edit runs 汇成一个可分页的列表。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Query

from . import ai_edit, store
from .agent import store as agent_store

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

ACTIVE = ("queued", "preparing", "uploading", "running", "waiting_confirm", "rendering")
KINDS = ("job", "render", "agent", "ai_edit")


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


def _collect_all(scan: int = 200) -> list[dict]:
    items: list[dict] = []

    for job in store.list_jobs(limit=scan)[0]:
        items.append({
            "id": job["id"], "kind": "job", "title": _job_title(job),
            "status": job["status"], "progress": job.get("progress") or 0,
            "message": job.get("message") or "", "error": job.get("error") or "",
            "created_at": job.get("created_at") or 0,
            "finished_at": job.get("finished_at") or 0,
            "project_id": job.get("project_id") or "",
            "shot_id": job.get("shot_id") or "",
            "outputs": job.get("outputs") or [],
            "cancelable": job["status"] in ACTIVE,
            "retryable": job["status"] in ("failed", "canceled"),
        })

    for render in store.list_renders_all(scan):
        items.append({
            "id": render["id"], "kind": "render", "title": _render_title(render),
            "status": render["status"], "progress": render.get("progress") or 0,
            "message": render.get("message") or "", "error": render.get("error") or "",
            "created_at": render.get("created_at") or 0,
            "finished_at": render.get("finished_at") or 0,
            "project_id": render.get("project_id") or "",
            "shot_id": "",
            "outputs": ([{"kind": "video", "url": f"/media/files/renders/{render['id']}/final.mp4"}]
                        if render["status"] == "succeeded" else []),
            "cancelable": render["status"] in ACTIVE,
            "retryable": render["status"] in ("failed", "canceled"),
        })

    for edit_run in ai_edit.list_runs(None, False, scan):
        state = edit_run.get("state") or {}
        done, total = state.get("done") or 0, state.get("total") or 0
        items.append({
            "id": edit_run["id"], "kind": "ai_edit", "title": "AI 剪辑",
            "status": edit_run["status"],
            "progress": done / max(1, total),
            "message": f"{done}/{total} 镜", "error": edit_run.get("error") or "",
            "created_at": edit_run.get("created_at") or 0,
            "finished_at": edit_run.get("finished_at") or 0,
            "project_id": edit_run.get("project_id") or "",
            "shot_id": "",
            "outputs": [],
            "cancelable": edit_run["status"] in ("running", "queued"),
            "retryable": edit_run["status"] in ("failed", "canceled"),
        })

    for run in agent_store.list_runs(None, scan):
        thread = agent_store.get_thread(run["thread_id"]) or {}
        items.append({
            "id": run["id"], "kind": "agent", "title": thread.get("title") or "导演助手",
            "status": run["status"], "progress": 0,
            "message": run.get("node") or "", "error": run.get("error") or "",
            "created_at": run.get("started_at") or 0,
            "finished_at": run.get("finished_at") or 0,
            "project_id": thread.get("project_id") or "",
            "shot_id": "",
            "thread_id": run["thread_id"],
            "outputs": [],
            "cancelable": run["status"] in ("running", "waiting_confirm"),
            "retryable": False,
        })

    items.sort(key=lambda i: i["created_at"], reverse=True)
    return items


TERMINAL = ("succeeded", "done", "failed", "canceled", "interrupted")


UNREAD_KINDS = ("job", "render", "ai_edit")


@router.get("/unread")
async def unread_tasks(since: float = 0.0) -> dict:
    """since 之后结束的「产出型」任务数，用于侧边栏角标。

    只统计生成 / 成片 / AI 剪辑；助手对话（agent）不计入——
    否则随便聊一句就会亮红点，角标就没有意义了。
    """
    items = _collect_all()
    # 取消/中断不算「有新结果」，只有成功或失败值得提示
    notify = {"succeeded", "done", "failed", "interrupted"}
    count = sum(1 for i in items
                if i["kind"] in UNREAD_KINDS
                and i["status"] in notify
                and (i.get("finished_at") or 0) > since)
    return {"count": count}


@router.get("")
async def list_tasks(
    kind: str = "",
    status: str = "",
    active_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    items = _collect_all()

    counts = {k: 0 for k in KINDS}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1

    if kind:
        wanted = {k.strip() for k in kind.split(",") if k.strip()}
        items = [i for i in items if i["kind"] in wanted]
    if status == "active":
        items = [i for i in items if i["status"] in ACTIVE]
    elif status == "done":
        items = [i for i in items if i["status"] in ("succeeded", "done")]
    elif status == "failed":
        items = [i for i in items if i["status"] in ("failed", "interrupted")]
    if active_only:
        items = [i for i in items if i["status"] in ACTIVE]

    total = len(items)
    page = items[offset:offset + limit]
    return {
        "items": page,
        "total": total,
        "counts": counts,
        "active": sum(1 for i in items if i["status"] in ACTIVE),
        "limit": limit,
        "offset": offset,
    }

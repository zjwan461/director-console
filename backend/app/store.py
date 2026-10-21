"""SQLite 持久层：项目 / 镜头 / 任务 / 素材。

设计原则：单文件、零外部依赖、可随时用 DB Browser 打开。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import settings

DB_PATH = Path(settings.paths["data"]) / "director.db"
_lock = threading.RLock()


def _now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """建表/升级全部交给 Alembic（见 app/migrate.py 与 backend/alembic/versions）。"""
    from .migrate import ensure_schema

    ensure_schema()
    with _lock, connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for key in ("inputs", "outputs", "meta", "shot_ids", "options"):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                pass
    if isinstance(d.get("values_json"), str):
        try:
            d["values"] = json.loads(d["values_json"])
        except Exception:
            d["values"] = {}
    d.pop("values_json", None)
    if isinstance(d.get("path"), str) and d["path"].startswith("data/"):
        d["path"] = d["path"][5:]
    return d


def _rows(rs: Iterable[sqlite3.Row]) -> list[dict]:
    return [_row(r) for r in rs]  # type: ignore[list-item]


# ---------------- projects ----------------
def create_project(name: str, style: str = "", notes: str = "") -> dict:
    pid = new_id("prj")
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO projects(id,name,style,notes,created_at) VALUES(?,?,?,?,?)",
            (pid, name, style, notes, _now()),
        )
    return get_project(pid)  # type: ignore[return-value]


def list_projects() -> list[dict]:
    with _lock, connect() as conn:
        return _rows(conn.execute("SELECT * FROM projects ORDER BY created_at DESC"))


def get_project(pid: str) -> dict | None:
    with _lock, connect() as conn:
        return _row(conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())


def delete_project(pid: str) -> None:
    with _lock, connect() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))


# ---------------- shots ----------------
def create_shot(project_id: str, title: str = "", preset_id: str = "", prompt: str = "") -> dict:
    sid = new_id("shot")
    with _lock, connect() as conn:
        idx = conn.execute(
            "SELECT COALESCE(MAX(idx),-1)+1 FROM shots WHERE project_id=?", (project_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO shots(id,project_id,idx,title,preset_id,prompt,created_at) VALUES(?,?,?,?,?,?,?)",
            (sid, project_id, idx, title, preset_id, prompt, _now()),
        )
    return get_shot(sid)  # type: ignore[return-value]


def list_shots(project_id: str) -> list[dict]:
    with _lock, connect() as conn:
        return _rows(
            conn.execute("SELECT * FROM shots WHERE project_id=? ORDER BY idx", (project_id,))
        )


def get_shot(sid: str) -> dict | None:
    with _lock, connect() as conn:
        return _row(conn.execute("SELECT * FROM shots WHERE id=?", (sid,)).fetchone())


def update_shot(sid: str, **fields: Any) -> None:
    allowed = {
        k: v for k, v in fields.items()
        if k in {"title", "preset_id", "prompt", "cover", "idx", "last_frame"}
    }
    if "values" in fields and fields["values"] is not None:
        allowed["values_json"] = json.dumps(fields["values"], ensure_ascii=False)
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE shots SET {sets} WHERE id=?", (*allowed.values(), sid))


def list_jobs_by_shot(shot_id: str, limit: int = 20) -> list[dict]:
    with _lock, connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM jobs WHERE shot_id=? ORDER BY created_at DESC LIMIT ?", (shot_id, limit)
        ))


def reorder_shots(project_id: str, ordered_ids: list[str]) -> list[dict]:
    with _lock, connect() as conn:
        valid = {r["id"] for r in conn.execute("SELECT id FROM shots WHERE project_id=?", (project_id,))}
        idx = 0
        for sid in ordered_ids:
            if sid not in valid:
                continue
            conn.execute("UPDATE shots SET idx=? WHERE id=?", (idx, sid))
            idx += 1
    return list_shots(project_id)


def delete_shot(sid: str) -> None:
    with _lock, connect() as conn:
        conn.execute("DELETE FROM shots WHERE id=?", (sid,))


# ---------------- render_shots ----------------
def save_render_shots(render_id: str, edits: list[dict]) -> None:
    with _lock, connect() as conn:
        conn.execute("DELETE FROM render_shots WHERE render_id=?", (render_id,))
        for idx, item in enumerate(edits):
            conn.execute(
                "INSERT INTO render_shots(render_id,shot_id,idx,in_point,out_point,speed,"
                "volume_db,muted,voice_asset,subtitle) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    render_id, item.get("shot_id"), idx,
                    float(item.get("in_point") or 0),
                    item.get("out_point"),
                    float(item.get("speed") or 1),
                    float(item.get("volume_db") or 0),
                    1 if item.get("muted") else 0,
                    str(item.get("voice_asset") or ""),
                    str(item.get("subtitle") or ""),
                ),
            )


def list_render_shots(render_id: str) -> list[dict]:
    with _lock, connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM render_shots WHERE render_id=? ORDER BY idx", (render_id,)
        ))


# ---------------- assets ----------------
def add_asset(kind: str, path: str, comfy_name: str = "", size: int = 0, width: int = 0, height: int = 0, meta: dict | None = None) -> dict:
    aid = new_id("ast")
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO assets(id,kind,path,comfy_name,width,height,size,meta,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (aid, kind, path, comfy_name, width, height, size, json.dumps(meta or {}), _now()),
        )
    return get_asset(aid)  # type: ignore[return-value]


def get_asset(aid: str) -> dict | None:
    with _lock, connect() as conn:
        return _row(conn.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone())


def list_assets(kind: str | None = None, limit: int = 100, offset: int = 0, q: str = "") -> list[dict]:
    items, _ = search_assets(kind, q, limit, offset)
    return items


def search_assets(kind: str | None = None, q: str = "", limit: int = 60, offset: int = 0) -> tuple[list[dict], int]:
    where = []
    params: list = []
    if kind:
        where.append("kind=?")
        params.append(kind)
    if q:
        where.append("path LIKE ?")
        params.append(f"%{q}%")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with _lock, connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM assets{clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM assets{clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return _rows(rows), int(total)


def find_asset_by_path(path: str) -> dict | None:
    with _lock, connect() as conn:
        return _row(conn.execute("SELECT * FROM assets WHERE path=?", (path,)).fetchone())


# ---------------- jobs ----------------
def create_job(preset_id: str, inputs: dict, project_id: str = "", shot_id: str = "") -> dict:
    jid = new_id("job")
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO jobs(id,project_id,shot_id,preset_id,status,progress,message,inputs,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (jid, project_id, shot_id, preset_id, "queued", 0, "排队中", json.dumps(inputs, ensure_ascii=False), _now()),
        )
    return get_job(jid)  # type: ignore[return-value]


def update_job(jid: str, **fields: Any) -> None:
    if "outputs" in fields and not isinstance(fields["outputs"], str):
        fields["outputs"] = json.dumps(fields["outputs"], ensure_ascii=False)
    if "inputs" in fields and not isinstance(fields["inputs"], str):
        fields["inputs"] = json.dumps(fields["inputs"], ensure_ascii=False)
    allowed = {
        "status", "progress", "message", "comfy_prompt_id", "inputs",
        "outputs", "error", "started_at", "finished_at", "project_id", "shot_id",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", (*fields.values(), jid))


def get_job(jid: str) -> dict | None:
    with _lock, connect() as conn:
        return _row(conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())


def _job_cursor(job: dict) -> str:
    """游标 = created_at:id，配合 (created_at, id) 降序稳定分页。"""
    return f"{job['created_at']}:{job['id']}"


def _parse_job_cursor(cursor: str) -> tuple[float | None, str]:
    ts, _, cid = cursor.partition(":")
    try:
        return float(ts), cid
    except ValueError:
        return None, ""


def list_jobs(
    limit: int = 50,
    status: str | None = None,
    cursor: str | None = None,
) -> tuple[list[dict], bool, str | None]:
    """按 created_at DESC 游标分页，返回 (items, has_more, next_cursor)。

    游标分页比 offset 更适合“滚动到底部加载更多”：新任务插入头部时
    不会造成老数据重复或漏读。
    """
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if cursor:
        ts, cid = _parse_job_cursor(cursor)
        if ts is not None:
            clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
            params.extend([ts, ts, cid])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _lock, connect() as conn:
        rows = _rows(conn.execute(
            f"SELECT * FROM jobs{where} ORDER BY created_at DESC, id DESC LIMIT ?",
            (*params, limit + 1),
        ))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _job_cursor(rows[-1]) if (has_more and rows) else None
    return rows, has_more, next_cursor


def recover_jobs() -> None:
    """进程重启后，把仍在中间态的任务标为失败，避免前端永远转圈。"""
    with _lock, connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='failed', error='服务重启导致中断', finished_at=? "
            "WHERE status IN ('queued','uploading','running')",
            (_now(),),
        )


# ---------------- settings ----------------
def get_setting(key: str, default: str = "") -> str:
    with _lock, connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now()),
        )


def list_settings() -> dict[str, str]:
    with _lock, connect() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings")}


def delete_setting(key: str) -> None:
    with _lock, connect() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))

# ---------------- renders ----------------
def create_render(project_id: str, shot_ids: list[str], options: dict) -> dict:
    rid = new_id("rnd")
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO renders(id,project_id,status,progress,message,shot_ids,options,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (rid, project_id, "queued", 0, "排队中",
             json.dumps(shot_ids, ensure_ascii=False),
             json.dumps(options, ensure_ascii=False), _now()),
        )
    return get_render(rid)  # type: ignore[return-value]


def update_render(rid: str, **fields: Any) -> None:
    if "options" in fields and not isinstance(fields["options"], str):
        fields["options"] = json.dumps(fields["options"], ensure_ascii=False)
    allowed = {
        "status", "progress", "message", "shot_ids", "options",
        "output_path", "cover_path", "error", "started_at", "finished_at",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE renders SET {sets} WHERE id=?", (*fields.values(), rid))


def get_render(rid: str) -> dict | None:
    with _lock, connect() as conn:
        return _row(conn.execute("SELECT * FROM renders WHERE id=?", (rid,)).fetchone())


def list_renders(project_id: str, limit: int = 20) -> list[dict]:
    with _lock, connect() as conn:
        return _rows(conn.execute(
            "SELECT * FROM renders WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        ))


def list_renders_all(limit: int = 50, status: str | None = None) -> list[dict]:
    with _lock, connect() as conn:
        if status:
            rows = conn.execute(
                "SELECT r.*, p.name AS project_name FROM renders r "
                "LEFT JOIN projects p ON p.id = r.project_id "
                "WHERE r.status=? ORDER BY r.created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            rows = conn.execute(
                "SELECT r.*, p.name AS project_name FROM renders r "
                "LEFT JOIN projects p ON p.id = r.project_id "
                "ORDER BY r.created_at DESC LIMIT ?",
                (limit,),
            )
        return _rows(rows)


def recover_renders() -> None:
    with _lock, connect() as conn:
        conn.execute(
            "UPDATE renders SET status='failed', error='服务重启导致中断', finished_at=? "
            "WHERE status IN ('queued','preparing','rendering')",
            (_now(),),
        )

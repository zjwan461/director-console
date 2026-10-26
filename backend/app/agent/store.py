"""agent 线程/消息/运行/产物的持久层。"""
from __future__ import annotations

import json
import time
from typing import Any

from ..store import _lock, connect, new_id


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- #
# 线程
# --------------------------------------------------------------------------- #
def create_thread(project_id: str, title: str = "新对话", model: str = "") -> dict:
    tid = new_id("th")
    now = _now()
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO agent_threads(id, title, project_id, model, created_at, updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (tid, title, project_id, model, now, now),
        )
    return get_thread(tid) or {}


def get_thread(thread_id: str) -> dict | None:
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM agent_threads WHERE id=?", (thread_id,)).fetchone()
    return _thread_row(row)


def list_threads(project_id: str | None = None, limit: int = 30) -> list[dict]:
    sql = "SELECT t.*, (SELECT content FROM agent_messages m WHERE m.thread_id=t.id" \
          " AND m.role='user' ORDER BY m.seq LIMIT 1) AS first_user" \
          " FROM agent_threads t WHERE t.archived=0"
    params: list[Any] = []
    if project_id:
        sql += " AND t.project_id=?"
        params.append(project_id)
    sql += " ORDER BY t.updated_at DESC LIMIT ?"
    params.append(limit)
    with _lock, connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for row in rows:
        item = _thread_row(row) or {}
        item["preview"] = (row["first_user"] or "")[:60]
        out.append(item)
    return out


def update_thread(thread_id: str, title: str | None = None, archived: int | None = None) -> dict | None:
    sets, params = [], []
    if title is not None:
        sets.append("title=?")
        params.append(title[:80])
    if archived is not None:
        sets.append("archived=?")
        params.append(int(archived))
    if not sets:
        return get_thread(thread_id)
    sets.append("updated_at=?")
    params.append(_now())
    params.append(thread_id)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE agent_threads SET {', '.join(sets)} WHERE id=?", params)
    return get_thread(thread_id)


def touch_thread(thread_id: str) -> None:
    with _lock, connect() as conn:
        conn.execute("UPDATE agent_threads SET updated_at=? WHERE id=?", (_now(), thread_id))


def get_context(thread_id: str) -> dict:
    """跨轮次上下文：最近产物、最近的提议。

    下一轮说「可以/就用这张图/开始吧」时，靠它直接推进，而不是让模型重新猜意图。
    """
    with _lock, connect() as conn:
        row = conn.execute("SELECT context_json FROM agent_threads WHERE id=?",
                           (thread_id,)).fetchone()
    if not row:
        return {}
    try:
        data = json.loads(row["context_json"] or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_context(thread_id: str, patch: dict) -> dict:
    ctx = get_context(thread_id)
    ctx.update(patch or {})
    with _lock, connect() as conn:
        conn.execute("UPDATE agent_threads SET context_json=? WHERE id=?",
                     (json.dumps(ctx, ensure_ascii=False), thread_id))
    return ctx


def delete_thread(thread_id: str) -> None:
    with _lock, connect() as conn:
        conn.execute("DELETE FROM agent_artifacts WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM agent_messages WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM agent_runs WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM agent_threads WHERE id=?", (thread_id,))


def _thread_row(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "title": row["title"],
        "project_id": row["project_id"],
        "model": row["model"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "archived": bool(row["archived"]),
        "context": _load_context(row),
    }


def _load_context(row) -> dict:
    try:
        keys = row.keys()
    except Exception:
        return {}
    if "context_json" not in keys:
        return {}
    try:
        data = json.loads(row["context_json"] or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# 消息
# --------------------------------------------------------------------------- #
def add_message(thread_id: str, role: str, content: str = "",
                parts: list[dict] | None = None, run_id: str = "") -> dict:
    mid = new_id("msg")
    with _lock, connect() as conn:
        seq = (conn.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM agent_messages WHERE thread_id=?",
            (thread_id,)).fetchone()[0]) + 1
        conn.execute(
            "INSERT INTO agent_messages(id, thread_id, run_id, role, content, parts_json, seq, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (mid, thread_id, run_id, role, content, json.dumps(parts or [], ensure_ascii=False),
             seq, _now()),
        )
        conn.execute("UPDATE agent_threads SET updated_at=? WHERE id=?", (_now(), thread_id))
    return get_message(mid) or {}


def get_message(message_id: str) -> dict | None:
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM agent_messages WHERE id=?", (message_id,)).fetchone()
    return _message_row(row)


def list_messages(thread_id: str, after_seq: int = 0, limit: int = 200) -> list[dict]:
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_messages WHERE thread_id=? AND seq>? ORDER BY seq LIMIT ?",
            (thread_id, after_seq, limit)).fetchall()
    return [_message_row(r) for r in rows]


def _message_row(row) -> dict | None:
    if row is None:
        return None
    try:
        parts = json.loads(row["parts_json"] or "[]")
    except Exception:
        parts = []
    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "run_id": row["run_id"],
        "role": row["role"],
        "content": row["content"],
        "parts": parts,
        "seq": row["seq"],
        "created_at": row["created_at"],
    }


# --------------------------------------------------------------------------- #
# 运行
# --------------------------------------------------------------------------- #
def create_run(thread_id: str) -> dict:
    rid = new_id("run")
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO agent_runs(id, thread_id, status, node, state_json, pending_json,"
            " error, steps, started_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, thread_id, "running", "", "{}", "{}", "", 0, _now()),
        )
    return get_run(rid) or {}


def get_run(run_id: str) -> dict | None:
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE id=?", (run_id,)).fetchone()
    return _run_row(row)


def update_run(run_id: str, **fields) -> dict | None:
    allowed = {"status", "node", "state_json", "pending_json", "error", "steps", "finished_at"}
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key}=?")
        if key in {"state_json", "pending_json"} and not isinstance(value, str):
            params.append(json.dumps(value, ensure_ascii=False))
        else:
            params.append(value)
    if not sets:
        return get_run(run_id)
    params.append(run_id)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE agent_runs SET {', '.join(sets)} WHERE id=?", params)
    return get_run(run_id)


def list_active_runs(thread_id: str) -> list[dict]:
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE thread_id=? AND status IN ('running','waiting_confirm')"
            " ORDER BY started_at DESC", (thread_id,)).fetchall()
    return [_run_row(r) for r in rows]


def _run_row(row) -> dict | None:
    if row is None:
        return None

    def _load(text: str) -> dict:
        try:
            data = json.loads(text or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    return {
        "id": row["id"],
        "thread_id": row["thread_id"],
        "status": row["status"],
        "node": row["node"],
        "state": _load(row["state_json"]),
        "pending": _load(row["pending_json"]),
        "error": row["error"],
        "steps": row["steps"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


# --------------------------------------------------------------------------- #
# 产物
# --------------------------------------------------------------------------- #
def add_artifact(run_id: str, thread_id: str, kind: str, ref_id: str = "",
                 url: str = "", meta: dict | None = None) -> dict:
    aid = new_id("art")
    with _lock, connect() as conn:
        conn.execute(
            "INSERT INTO agent_artifacts(id, run_id, thread_id, kind, ref_id, url, meta_json, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (aid, run_id, thread_id, kind, ref_id, url,
             json.dumps(meta or {}, ensure_ascii=False), _now()),
        )
    return get_artifact(aid) or {}


def get_artifact(artifact_id: str) -> dict | None:
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM agent_artifacts WHERE id=?", (artifact_id,)).fetchone()
    return _artifact_row(row)


def find_artifact(thread_id: str, ref_id: str) -> dict | None:
    """同一个 job/render 只保留一条产物记录。"""
    with _lock, connect() as conn:
        row = conn.execute(
            "SELECT * FROM agent_artifacts WHERE thread_id=? AND ref_id=?"
            " ORDER BY created_at DESC LIMIT 1", (thread_id, ref_id)).fetchone()
    return _artifact_row(row)


def update_artifact(artifact_id: str, url: str | None = None,
                    meta: dict | None = None, kind: str | None = None) -> dict | None:
    sets, params = [], []
    if url is not None:
        sets.append("url=?")
        params.append(url)
    if kind:
        sets.append("kind=?")
        params.append(kind)
    if meta is not None:
        sets.append("meta_json=?")
        params.append(json.dumps(meta, ensure_ascii=False))
    if not sets:
        return get_artifact(artifact_id)
    params.append(artifact_id)
    with _lock, connect() as conn:
        conn.execute(f"UPDATE agent_artifacts SET {', '.join(sets)} WHERE id=?", params)
    return get_artifact(artifact_id)


def dedupe_artifacts(thread_id: str) -> int:
    """清掉同 ref_id 的重复占位记录（保留最新一条）。"""
    removed = 0
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT id, ref_id FROM agent_artifacts WHERE thread_id=?"
            " ORDER BY created_at DESC", (thread_id,)).fetchall()
        seen: set[str] = set()
        for row in rows:
            ref = row["ref_id"] or ""
            if not ref:
                continue
            if ref in seen:
                conn.execute("DELETE FROM agent_artifacts WHERE id=?", (row["id"],))
                removed += 1
            else:
                seen.add(ref)
    return removed


def list_artifacts(thread_id: str, limit: int = 50) -> list[dict]:
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_artifacts WHERE thread_id=? ORDER BY created_at DESC LIMIT ?",
            (thread_id, limit)).fetchall()
    return [_artifact_row(r) for r in rows]


def _artifact_row(row) -> dict | None:
    if row is None:
        return None
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except Exception:
        meta = {}
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "thread_id": row["thread_id"],
        "kind": row["kind"],
        "ref_id": row["ref_id"],
        "url": row["url"],
        "meta": meta,
        "created_at": row["created_at"],
    }

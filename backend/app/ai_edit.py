"""AI 剪辑（批量）：复用 main 里的 AI 端点，改成服务端跑 + 进度推送。

为什么不重写业务逻辑：字幕要判「旁白是否对得上画面」「有没有人声」「ASR 转写」，
这些规则已经写在 /api/ai/script 里。这里只负责编排与落库，避免两份实现漂移。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from . import store
from .agent.events import bus


def _new_id() -> str:
    return "aied_" + uuid.uuid4().hex[:12]


def _load_state(project_id: str) -> dict:
    raw = store.get_setting(f"edit_state.{project_id}", "")
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("options", {})
    data.setdefault("shot_edits", [])
    return data


def _save_state(project_id: str, state: dict) -> None:
    store.set_setting(f"edit_state.{project_id}", json.dumps(state, ensure_ascii=False))


def _edit_map(state: dict) -> dict[str, dict]:
    return {str(e.get("shot_id")): e for e in (state.get("shot_edits") or []) if e.get("shot_id")}


def _duration_of(edit: dict) -> float:
    out_point = float(edit.get("out_point") or 0)
    in_point = float(edit.get("in_point") or 0)
    return max(0.5, out_point - in_point) if out_point > in_point else 5.0


SPEED_STEPS = [1.0, 1.05, 1.1, 1.15, 1.2, 1.25]


# --------------------------------------------------------------------------- #
# 运行记录
# --------------------------------------------------------------------------- #
def create_run(project_id: str, shot_ids: list[str], options: dict) -> dict:
    rid = _new_id()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO ai_edit_runs(id, project_id, status, shot_ids, options_json,"
            " state_json, error, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, project_id, "running", json.dumps(shot_ids, ensure_ascii=False),
             json.dumps(options, ensure_ascii=False), "{}", "", time.time(), time.time()),
        )
    return get_run(rid) or {}


def get_run(run_id: str) -> dict | None:
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM ai_edit_runs WHERE id=?", (run_id,)).fetchone()
    return _row(row)


def list_runs(project_id: str | None = None, active_only: bool = False, limit: int = 20) -> list[dict]:
    sql = "SELECT * FROM ai_edit_runs"
    where, params = [], []
    if project_id:
        where.append("project_id=?")
        params.append(project_id)
    if active_only:
        where.append("status IN ('running','queued')")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with store.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r) for r in rows if r is not None]


def update_run(run_id: str, **fields) -> None:
    allowed = {"status", "state_json", "error", "updated_at"}
    sets, params = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key}=?")
        params.append(json.dumps(value, ensure_ascii=False)
                      if key == "state_json" and not isinstance(value, str) else value)
    if not sets:
        return
    sets.append("updated_at=?")
    params.extend([time.time(), run_id])
    with store.connect() as conn:
        conn.execute(f"UPDATE ai_edit_runs SET {', '.join(sets)} WHERE id=?", params)


def _row(row) -> dict | None:
    if row is None:
        return None

    def load(text: str, default: Any) -> Any:
        try:
            return json.loads(text or "")
        except Exception:
            return default

    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "status": row["status"],
        "shot_ids": load(row["shot_ids"], []),
        "options": load(row["options_json"], {}),
        "state": load(row["state_json"], {}),
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# --------------------------------------------------------------------------- #
# 执行
# --------------------------------------------------------------------------- #
async def start(project_id: str, shot_ids: list[str], options: dict) -> dict:
    import asyncio

    if not store.get_project(project_id):
        raise ValueError("项目不存在")
    shots = store.list_shots(project_id)
    valid = {s["id"] for s in shots}
    targets = [sid for sid in shot_ids if sid in valid] or [s["id"] for s in shots]
    if not targets:
        raise ValueError("项目里还没有镜头")

    run = create_run(project_id, targets, options)
    asyncio.create_task(_guarded(run["id"], project_id, targets, options))
    return run


async def _guarded(run_id: str, project_id: str, targets: list[str], options: dict) -> None:
    """任何异常都要让任务收尾，否则前端会一直等。"""
    try:
        await _execute(run_id, project_id, targets, options)
    except Exception as exc:
        update_run(run_id, status="failed", error=str(exc)[:500])
        bus.publish(run_id, {"t": "error", "text": f"执行失败：{str(exc)[:200]}"})


async def _execute(run_id: str, project_id: str, shot_ids: list[str], options: dict) -> None:
    # 延迟导入：main 在模块加载时会 include 本模块的路由，顶层导入会成环
    from .main import ScriptRequest, TTSRequest, TitleRequest, ai_bgm_plan, ai_script_one, ai_title, ai_tts

    kind = str(options.get("kind") or "both")
    mode = str(options.get("mode") or "fill")
    systems = options.get("systems") or {}
    outline = str(options.get("outline") or "")
    frames = int(options.get("frames") or 0)
    styles = options.get("styles") or {}
    tts_on = bool(options.get("tts", True))
    auto_speed = bool(options.get("auto_speed", True))
    titles_on = bool(options.get("titles", True))
    auto_bgm = bool(options.get("auto_bgm", False))
    bgm_asset_id = str(options.get("bgm_asset_id") or "")

    state = _load_state(project_id)
    edits = _edit_map(state)
    shots = store.list_shots(project_id)
    by_id = {s["id"]: s for s in shots}

    done = 0
    failed = 0
    tts_failed = 0
    rows: dict[str, dict] = {}

    def emit(event: dict) -> None:
        bus.publish(run_id, event)

    emit({"t": "start", "run_id": run_id, "total": len(shot_ids), "kind": kind})

    for index, sid in enumerate(shot_ids):
        shot = by_id.get(sid)
        if not shot:
            continue
        edit = dict(edits.get(sid) or {"shot_id": sid})
        title = shot.get("title") or f"镜头 {shot.get('idx', index) + 1}"
        emit({"t": "row", "shot_id": sid, "title": title, "status": "running", "note": ""})
        started = time.time()
        notes: list[str] = []
        duration = _duration_of(edit)

        narration_on = bool(edit.get("narration_on"))
        lip_on = bool(edit.get("lip_on"))
        burned = bool(edit.get("burned_subtitle"))
        want_sub = (not burned) and (narration_on or lip_on) and kind != "narration"
        want_narr = narration_on and kind in ("both", "narration")

        narration_text = str(edit.get("narration") or "")
        need_narr = want_narr and (mode == "rewrite" or not narration_text)
        need_sub = want_sub and (mode == "rewrite" or not str(edit.get("subtitle") or ""))

        if need_narr:
            try:
                result = await ai_script_one(ScriptRequest(
                    shot_id=sid, kind="narration", mode=mode, frames=frames,
                    style=styles.get("narration") or {},
                    system_prompt=systems.get("narration") or None,
                    outline=outline or None))
                narration_text = str(result.get("text") or "")
                edit["narration"] = narration_text
                done += 1
                notes.append(f"旁白 {result.get('chars', len(narration_text))}/{result.get('budget', '?')} 字")
            except Exception as exc:
                failed += 1
                notes.append("旁白失败：" + str(exc)[:60])

        if need_sub:
            try:
                result = await ai_script_one(ScriptRequest(
                    shot_id=sid, kind="subtitle", mode=mode, frames=frames,
                    narration=narration_text if narration_on else ("" if lip_on else ""),
                    style=styles.get("subtitle") or {},
                    system_prompt=systems.get("subtitle") or None,
                    outline=outline or None))
                if result.get("skip") == "silent":
                    notes.append("无口播，跳过字幕")
                else:
                    edit["subtitle"] = str(result.get("text") or "")
                    done += 1
                    notes.append(f"字幕 {result.get('chars', 0)}/{result.get('budget', '?')} 字")
            except Exception as exc:
                failed += 1
                notes.append("字幕失败：" + str(exc)[:60])

        if need_narr and tts_on and narration_text:
            try:
                audio = await ai_tts(TTSRequest(text=narration_text, shot_id=sid,
                                                voice=edit.get("tts_voice") or None))
                edit["voice_asset"] = audio.get("asset_id") or ""
                voice_dur = float(audio.get("duration") or 0)
                notes.append(f"配音 {round(voice_dur, 2)}s")
                if auto_speed and voice_dur > 0:
                    slot = float(audio.get("slot") or duration)
                    ratio = voice_dur / max(slot - 0.3, 0.5) if slot > 0.5 else 1
                    speed = next((v for v in SPEED_STEPS if v >= ratio), 1.0)
                    if speed > 1.0 and slot >= 1.5:
                        edit["speed"] = str(speed)
                        notes.append(f"画面 {speed:.2f}x 对齐旁白")
                    elif ratio > 1.25:
                        notes.append("旁白超 1.25x 仍放不下，建议缩短文案")
            except Exception as exc:
                tts_failed += 1
                notes.append("配音失败：" + str(exc)[:50])

        if not need_sub and not need_narr:
            notes.append("已有内容，跳过")

        edits[sid] = edit
        state["shot_edits"] = list(edits.values())
        _save_state(project_id, state)

        ok = not any("失败" in n for n in notes)
        row = {"shot_id": sid, "title": title, "status": "done" if ok else "error",
               "note": " · ".join(notes), "seconds": round(time.time() - started, 1)}
        rows[sid] = row
        emit({"t": "row", **row})
        emit({"t": "progress", "done": index + 1, "total": len(shot_ids),
              "failed": failed, "tts_failed": tts_failed})
        update_run(run_id, state_json={"rows": rows, "done": index + 1, "total": len(shot_ids)})

    if auto_bgm or bgm_asset_id:
        try:
            options_state = dict(state.get("options") or {})
            if auto_bgm:
                plan = await ai_bgm_plan(TitleRequest(project_id=project_id))
                options_state["bgm_tracks"] = plan.get("tracks") or []
                emit({"t": "bgm", "mode": "auto", "notes": plan.get("notes") or [],
                      "tracks": plan.get("tracks") or []})
            else:
                has_narration = any((edits.get(s["id"]) or {}).get("narration_on") for s in shots)
                options_state["bgm_tracks"] = [{
                    "id": f"t{int(time.time())}",
                    "asset_id": bgm_asset_id,
                    "volume_db": -18 if has_narration else -12,
                    "start": 0, "end": None, "fade_in": 1, "fade_out": 2, "loop": True,
                }]
                emit({"t": "bgm", "mode": "single", "tracks": options_state["bgm_tracks"]})
            state["options"] = options_state
            _save_state(project_id, state)
            done += 1
        except Exception as exc:
            failed += 1
            emit({"t": "notice", "level": "err", "text": "配乐失败：" + str(exc)[:80]})

    if titles_on:
        try:
            title_text = await ai_title(TitleRequest(project_id=project_id, kind="title"))
            tail_text = await ai_title(TitleRequest(project_id=project_id, kind="tail"))
            options_state = dict(state.get("options") or {})
            options_state["title"] = {**(options_state.get("title") or {}),
                                      "text": (title_text or {}).get("text", ""), "enabled": True}
            options_state["tail"] = {**(options_state.get("tail") or {}),
                                     "text": (tail_text or {}).get("text", ""), "enabled": True}
            state["options"] = options_state
            _save_state(project_id, state)
            done += 1
            emit({"t": "titles", "title": (title_text or {}).get("text", ""),
                  "tail": (tail_text or {}).get("text", "")})
        except Exception as exc:
            failed += 1
            emit({"t": "notice", "level": "err", "text": "片头片尾生成失败：" + str(exc)[:80]})

    summary = f"成功 {done} 项"
    if failed:
        summary += f"，失败 {failed} 项"
    if tts_failed:
        summary += f"，配音失败 {tts_failed} 项"
    update_run(run_id, status="done",
               state_json={"rows": rows, "done": len(shot_ids), "total": len(shot_ids)})
    emit({"t": "done", "summary": summary, "failed": failed, "tts_failed": tts_failed})

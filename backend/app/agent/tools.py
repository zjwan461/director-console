"""M1 工具：环境探测、素材检索、提交图片生成、查任务。

设计约定
- 生成类工具是 async（要 await runner.enqueue）
- 返回 JSON 字符串（LangChain tool content 是文本）
- 关键动作只负责"提交"，不等结果
- 不抛异常给模型：失败也返回 {"ok": false, "error": ..., "hint": ...}
- inputs 存的是**语义值**（prompt / size{aspect,megapixels} / seed），
  由 presets.build_bindings 在提交时翻译成节点绑定
"""
from __future__ import annotations

import json
from typing import Any

from .. import store
from ..jobs import runner
from ..render import runner as render_runner
from ..presets import (build_bindings, get_card, is_video_card, load_cards, public_card,
                       size_from, validate)

IMAGE_CARD_ID = "image.c16"

# 视频模式 -> (能力卡, 必填的图片槽位)
VIDEO_CARDS = {
    "t2v": ("h3.t2v", ""),
    "i2v": ("h3.i2v", "first_frame"),
    "r2v": ("h3.r2v", "ref_1"),
}
VIDEO_MAX_DURATION = 15

ASPECT_RATIO: dict[str, tuple[int, int]] = {
    "16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1),
    "4:3": (4, 3), "3:4": (3, 4), "21:9": (21, 9), "3:2": (3, 2), "2:3": (2, 3),
}


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _card_field(card: dict, key: str) -> dict:
    for field in card.get("fields") or []:
        if field.get("key") == key:
            return field
    return {}


def default_megapixels(card: dict) -> float:
    field = _card_field(card, "size")
    return float(field.get("default_megapixels") or 1.0)


def build_values(card: dict, *, prompt: str, aspect: str, megapixels: float | None = None,
                 seed: int = -1) -> dict[str, Any]:
    """构造能力卡的语义值（不是节点绑定）。"""
    size_field = _card_field(card, "size")
    aspect = aspect if aspect in ASPECT_RATIO else str(size_field.get("default_aspect") or "16:9")
    mp = float(megapixels or size_field.get("default_megapixels") or 1.0)
    values: dict[str, Any] = {"prompt": str(prompt or "").strip()}
    if size_field:
        values["size"] = {"aspect": aspect, "megapixels": mp}
    if _card_field(card, "seed"):
        values["seed"] = int(seed)
    return values


def image_inputs_preview(prompt: str, aspect: str = "9:16", megapixels: float | None = None,
                         seed: int = -1) -> dict:
    """给确认卡用：算出最终输入与尺寸，不提交。"""
    card = get_card(IMAGE_CARD_ID) or {}
    if not card:
        return {"preset_id": IMAGE_CARD_ID, "params": {}, "binds": {},
                "errors": ["图片能力卡不存在"]}
    values = build_values(card, prompt=prompt, aspect=aspect, megapixels=megapixels, seed=seed)
    errors = validate(card, values)
    binds = build_bindings(card, values, {}) if not errors else {}
    aspect_used = values.get("size", {}).get("aspect")
    mp = values.get("size", {}).get("megapixels")
    width, height = size_from(aspect_used, mp) if aspect_used and mp else (0, 0)
    return {
        "preset_id": IMAGE_CARD_ID,
        "params": {
            "prompt": values["prompt"],
            "aspect": aspect_used,
            "megapixels": mp,
            "width": width,
            "height": height,
            "seed": values.get("seed", seed),
        },
        "megapixels_options": size_field.get("megapixels_options") or [1.0, 2.0],
        "binds": binds,
        "errors": errors,
    }


# --------------------------------------------------------------------------- #
# 只读
# --------------------------------------------------------------------------- #
def env_check() -> str:
    presets = []
    for card in load_cards():
        if not card.get("_workflow_exists"):
            continue
        public = public_card(card)
        presets.append({
            "id": public.get("id"),
            "name": public.get("name"),
            "category": public.get("category"),
            "output_kind": public.get("output_kind"),
        })
    card = get_card(IMAGE_CARD_ID) or {}
    size_field = _card_field(card, "size")
    return _dumps({
        "ok": True,
        "presets": presets,
        "image_card": IMAGE_CARD_ID,
        "image_card_name": card.get("name", ""),
        "aspects": list(ASPECT_RATIO.keys()),
        "default_aspect": size_field.get("default_aspect", "16:9"),
        "default_megapixels": default_megapixels(card) if card else 1.0,
        "megapixels_options": size_field.get("megapixels_options") or [],
    })


def list_assets(kind: str = "", q: str = "", purpose: str = "", limit: int = 10) -> str:
    limit = max(1, min(int(limit or 10), 30))
    items, total = store.search_assets(kind or None, q or "", limit, 0, purpose or None)
    out = [{
        "id": item["id"],
        "kind": item["kind"],
        "path": item["path"],
        "url": f"/media/files/{item['path']}",
        "purpose": (item.get("meta") or {}).get("purpose", ""),
        "width": item.get("width"),
        "height": item.get("height"),
        "size": item.get("size"),
    } for item in items]
    return _dumps({"ok": True, "total": total, "items": out})


def job_status(job_id: str) -> str:
    job = store.get_job(job_id)
    if not job:
        return _dumps({"ok": False, "error": "job_not_found",
                       "hint": f"没有 id 为 {job_id} 的任务"})
    outputs = job.get("outputs") or []
    return _dumps({
        "ok": True,
        "job_id": job["id"],
        "status": job["status"],
        "progress": job.get("progress", 0),
        "message": job.get("message", ""),
        "error": job.get("error", ""),
        "outputs": outputs if isinstance(outputs, list) else [],
    })


# --------------------------------------------------------------------------- #
# 写（确认后执行）
# --------------------------------------------------------------------------- #
async def make_image(prompt: str, aspect: str = "9:16", megapixels: float | None = None,
                     seed: int = -1) -> str:
    preview = image_inputs_preview(prompt, aspect, megapixels, seed)
    if preview["errors"]:
        return _dumps({"ok": False, "error": "invalid_params",
                       "hint": "；".join(preview["errors"])})
    card = get_card(IMAGE_CARD_ID)
    if not card:
        return _dumps({"ok": False, "error": "card_missing",
                       "hint": f"图片能力卡 {IMAGE_CARD_ID} 不存在"})

    values = build_values(card, prompt=prompt, aspect=aspect, megapixels=megapixels, seed=seed)
    job = store.create_job(IMAGE_CARD_ID, values, "", "")
    try:
        await runner.enqueue(job["id"])
    except Exception as exc:
        return _dumps({"ok": False, "error": "enqueue_failed", "hint": str(exc),
                       "job_id": job["id"]})
    return _dumps({
        "ok": True,
        "job_id": job["id"],
        "preset_id": IMAGE_CARD_ID,
        "params": preview["params"],
    })


# --------------------------------------------------------------------------- #
# 视频（M2）
# --------------------------------------------------------------------------- #
def _card_default(card: dict, key: str, fallback=None):
    field = _card_field(card, key)
    return field.get("default", fallback)


def video_inputs_preview(prompt: str, mode: str = "t2v", aspect: str = "16:9",
                         duration: float | None = None,
                         image_asset_id: str = "",
                         megapixels: float | None = None) -> dict:
    """给确认卡用：算视频参数，不提交。"""
    card_id, image_slot = VIDEO_CARDS.get(mode, VIDEO_CARDS["t2v"])
    card = get_card(card_id)
    if not card:
        return {"preset_id": card_id, "errors": [f"能力卡 {card_id} 不存在"]}

    size_field = _card_field(card, "size")
    aspect = aspect if aspect in ASPECT_RATIO else str(size_field.get("default_aspect") or "16:9")
    mp = float(megapixels or size_field.get("default_megapixels") or 0.4)
    seconds = float(duration or _card_default(card, "duration", 5))
    lo = float(_card_field(card, "duration").get("min", 1))
    hi = float(_card_field(card, "duration").get("max", VIDEO_MAX_DURATION))
    seconds = max(lo, min(hi, seconds))

    values: dict[str, Any] = {
        "prompt": str(prompt or "").strip(),
        "size": {"aspect": aspect, "megapixels": mp},
        "duration": seconds,
    }
    if image_slot:
        values[image_slot] = image_asset_id or ""

    errors = validate(card, values)
    width, height = size_from(aspect, mp) if aspect else (0, 0)
    return {
        "preset_id": card_id,
        "mode": mode,
        "params": {
            "prompt": values["prompt"],
            "aspect": aspect,
            "duration": seconds,
            "megapixels": mp,
            "width": width,
            "height": height,
            "image_asset_id": image_asset_id,
        },
        "megapixels_options": size_field.get("megapixels_options") or [0.4, 0.8],
        "values": values,
        "errors": errors,
    }


async def make_video(prompt: str, mode: str = "t2v", aspect: str = "16:9",
                     duration: float | None = None, image_asset_id: str = "",
                     megapixels: float | None = None) -> str:
    preview = video_inputs_preview(prompt, mode, aspect, duration, image_asset_id, megapixels)
    if preview["errors"]:
        return _dumps({"ok": False, "error": "invalid_params",
                       "hint": "；".join(preview["errors"])})
    card_id = preview["preset_id"]
    job = store.create_job(card_id, preview["values"], "", "")
    try:
        await runner.enqueue(job["id"])
    except Exception as exc:
        return _dumps({"ok": False, "error": "enqueue_failed", "hint": str(exc),
                       "job_id": job["id"]})
    return _dumps({"ok": True, "job_id": job["id"], "preset_id": card_id,
                   "params": preview["params"]})


# --------------------------------------------------------------------------- #
# 成片导出（M2b）
# --------------------------------------------------------------------------- #
QUALITY = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "480p": (854, 480),
    "竖屏1080": (1080, 1920),
    "竖屏720": (720, 1280),
}


def _edit_state(project_id: str) -> dict:
    import json as _json

    raw = store.get_setting(f"edit_state.{project_id}", "")
    try:
        data = _json.loads(raw) if raw else {}
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def export_preview(project_id: str, quality: str = "1080p") -> dict:
    """给确认卡用：项目的镜头数、分辨率、预估时长。"""
    shots = store.list_shots(project_id)
    if not shots:
        return {"ok": False, "errors": ["项目里还没有镜头"]}
    width, height = QUALITY.get(quality, QUALITY["1080p"])
    state = _edit_state(project_id)
    options = state.get("options") or {}
    edits = {str(e.get("shot_id")): e for e in (state.get("shot_edits") or []) if e.get("shot_id")}

    total = 0.0
    for shot in shots:
        edit = edits.get(shot["id"], {})
        out_point = float(edit.get("out_point") or 0)
        in_point = float(edit.get("in_point") or 0)
        speed = float(edit.get("speed") or 1) or 1
        if out_point > in_point:
            total += (out_point - in_point) / speed
    return {
        "ok": True,
        "project_id": project_id,
        "shots": len(shots),
        "width": width,
        "height": height,
        "quality": quality,
        "subtitles": bool((options.get("subtitles") or {}).get("enabled")),
        "bgm": len(options.get("bgm_tracks") or []),
        "approx_seconds": round(total, 1),
        "eta": max(30, int(total * 3)),
    }


async def make_film(project_id: str, quality: str = "1080p") -> str:
    """按剪辑页的状态导出成片（全部镜头）。"""
    preview = export_preview(project_id, quality)
    if not preview.get("ok"):
        return _dumps({"ok": False, "error": "no_shots", "hint": "；".join(preview.get("errors") or [])})

    shots = store.list_shots(project_id)
    shot_ids = [s["id"] for s in shots]
    state = _edit_state(project_id)
    options = dict(state.get("options") or {})
    options["width"], options["height"] = preview["width"], preview["height"]
    options.setdefault("fps", 24)
    options.pop("preview", None)
    options.pop("cache_key", None)

    render = store.create_render(project_id, shot_ids, options)
    edits = [e for e in (state.get("shot_edits") or []) if e.get("shot_id") in set(shot_ids)]
    if edits:
        store.save_render_shots(render["id"], edits)
    try:
        await render_runner.enqueue(render["id"])
    except Exception as exc:
        return _dumps({"ok": False, "error": "enqueue_failed", "hint": str(exc),
                       "render_id": render["id"]})
    return _dumps({"ok": True, "render_id": render["id"], "params": preview})


# --------------------------------------------------------------------------- #
# 产物 → 镜头
# --------------------------------------------------------------------------- #
async def save_as_shot(job_id: str, project_id: str, title: str = "") -> str:
    job = store.get_job(job_id)
    if not job:
        return _dumps({"ok": False, "error": "job_not_found", "hint": "任务不存在"})
    if job.get("status") != "succeeded":
        return _dumps({"ok": False, "error": "not_finished", "hint": "任务还没成功，先等等"})
    if job.get("shot_id"):
        return _dumps({"ok": False, "error": "already_shot",
                       "hint": f"这个任务已经是镜头 {job['shot_id']} 了"})
    if not store.get_project(project_id):
        return _dumps({"ok": False, "error": "project_missing", "hint": "项目不存在"})
    card = get_card(job.get("preset_id") or "")
    if card and not is_video_card(card):
        return _dumps({"ok": False, "error": "image_card",
                       "hint": "这是图片卡生成的结果，不能直接存成镜头；可以把它当视频卡的首帧"})

    shot = store.create_shot(project_id, title or f"镜头 {len(store.list_shots(project_id)) + 1}",
                             job.get("preset_id") or "")
    store.update_shot(shot["id"], values=job.get("inputs") or {})
    store.update_job(job_id, project_id=project_id, shot_id=shot["id"])
    updated = store.get_job(job_id)
    if updated and updated.get("outputs"):
        try:
            await runner._attach_last_frame(updated, updated["outputs"])
        except Exception:
            pass
    return _dumps({"ok": True, "shot_id": shot["id"],
                   "title": title or "新镜头", "project_id": project_id})

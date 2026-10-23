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
from ..presets import build_bindings, get_card, load_cards, public_card, size_from, validate

IMAGE_CARD_ID = "image.c16"

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

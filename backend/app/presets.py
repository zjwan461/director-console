"""能力卡（preset）加载与参数绑定。

一张能力卡 = 一套 API 格式工作流 + 一份「创作者语言」的参数表。
前端只认能力卡，永远看不到节点 ID。
"""
from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path
from typing import Any

import yaml

from .config import settings

PRESET_DIR = Path(settings.paths["presets"])
WORKFLOW_DIR = Path(settings.paths["workflows"])

ASPECTS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "21:9": (21, 9),
}

ASPECT_LABELS = {
    "16:9 (Widescreen)": "16:9 横屏",
    "9:16 (Portrait Widescreen)": "9:16 竖屏",
    "1:1 (Square)": "1:1 方形",
    "4:3 (Standard)": "4:3 标准",
    "3:4 (Portrait Standard)": "3:4 竖版",
    "21:9 (Cinematic)": "21:9 宽银幕",
}

_DURATION_TYPES = {"duration", "seconds"}


def snap_frames(seconds: float, fps: int = 24) -> int:
    """H3 的合法帧数：4n+1，向上取整。"""
    raw = max(1, int(round(seconds * fps)))
    return ((raw - 1 + 3) // 4) * 4 + 1


def align32(value: int) -> int:
    return max(32, int(round(value / 32.0)) * 32)


def size_from(aspect: str, megapixels: float) -> tuple[int, int]:
    aw, ah = ASPECTS.get(aspect, (16, 9))
    total = max(0.05, float(megapixels)) * 1_000_000
    w = math.sqrt(total * aw / ah)
    h = w * ah / aw
    return align32(w), align32(h)


def load_workflow(name: str) -> dict:
    path = WORKFLOW_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"工作流不存在：{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_field(f: dict) -> dict:
    out = dict(f)
    out.setdefault("type", "text")
    out.setdefault("required", False)
    if out["type"] in _DURATION_TYPES:
        out.setdefault("min", 1)
        out.setdefault("max", 15)
        out.setdefault("default", 5)
    return out


def load_cards() -> list[dict]:
    cards: list[dict] = []
    if not PRESET_DIR.exists():
        return cards
    for path in sorted(PRESET_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # 坏卡片不应该拖垮整个面板
            cards.append({"id": path.stem, "name": path.stem, "error": f"YAML 解析失败：{exc}"})
            continue
        data.setdefault("id", path.stem)
        data.setdefault("name", path.stem)
        data.setdefault("desc", "")
        data.setdefault("badge", "")
        data.setdefault("order", 100)
        data["fields"] = [_normalize_field(f) for f in data.get("fields", [])]
        data["_file"] = path.name
        wf = data.get("workflow", "")
        data["_workflow_exists"] = bool(wf) and (WORKFLOW_DIR / wf).exists()
        if not data["_workflow_exists"]:
            data["error"] = f"工作流缺失：{wf}"
        cards.append(data)
    cards.sort(key=lambda c: (c.get("order", 100), c.get("id", "")))
    return cards


def get_card(card_id: str) -> dict | None:
    for card in load_cards():
        if card.get("id") == card_id:
            return card
    return None


def public_card(card: dict) -> dict:
    """给前端的能力卡：剔除内部字段，补上画幅/时长等派生信息。"""
    fields = []
    for f in card.get("fields", []):
        item = {k: v for k, v in f.items() if not k.startswith("_")}
        if item.get("type") == "size":
            item.setdefault("presets", [
                {"aspect": "16:9", "megapixels": 0.4, "label": "横屏 16:9"},
                {"aspect": "9:16", "megapixels": 0.4, "label": "竖屏 9:16"},
                {"aspect": "1:1", "megapixels": 0.4, "label": "方形 1:1"},
            ])
            item.setdefault("default_aspect", "16:9")
            item.setdefault("default_megapixels", 0.4)
        if item.get("type") in _DURATION_TYPES:
            item["frame_hint"] = snap_frames(float(item.get("default", 5)))
        fields.append(item)
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "badge": card.get("badge", ""),
        "desc": card.get("desc", ""),
        "hint": card.get("hint", ""),
        "category": card.get("category", "video"),
        "output_kind": card.get("output_kind", "video"),
        "fields": fields,
        "error": card.get("error", ""),
    }


def default_values(card: dict) -> dict:
    values: dict[str, Any] = {}
    for f in card.get("fields", []):
        key = f.get("key")
        if not key:
            continue
        if f.get("type") == "size":
            values[key] = {
                "aspect": f.get("default_aspect", "16:9"),
                "megapixels": f.get("default_megapixels", 0.4),
            }
        elif f.get("type") == "seed":
            values[key] = f.get("default", -1)
        elif "default" in f:
            values[key] = f["default"]
        elif f.get("type") in {"image", "video", "audio"}:
            values[key] = ""
        else:
            values[key] = ""
    return values


def validate(card: dict, values: dict) -> list[str]:
    errors: list[str] = []
    for f in card.get("fields", []):
        key = f.get("key")
        if not key:
            continue
        val = values.get(key)
        empty = val in (None, "", [], {})
        if f.get("required") and empty:
            errors.append(f"{f.get('label', key)} 必填")
        if f.get("type") in _DURATION_TYPES and not empty:
            try:
                seconds = float(val)
            except (TypeError, ValueError):
                errors.append(f"{f.get('label', key)} 必须是数字")
                continue
            lo, hi = float(f.get("min", 1)), float(f.get("max", 15))
            if not (lo <= seconds <= hi):
                errors.append(f"{f.get('label', key)} 需在 {lo:g}~{hi:g} 秒之间")
    return errors


def build_bindings(card: dict, values: dict, media: dict[str, str]) -> dict[str, Any]:
    """把用户输入翻译成 {节点ID:字段名: 值}。

    media: {field_key: comfy 输入文件名}
    """
    binds: dict[str, Any] = {}
    for f in card.get("fields", []):
        key = f.get("key") or ""
        ftype = f.get("type", "text")
        val = values.get(key)

        if ftype in {"image", "video", "audio"}:
            name = media.get(key) or ""
            if name and f.get("bind"):
                binds[f["bind"]] = name
            continue

        if ftype == "size":
            mode = f.get("mode", "wh")
            size = val if isinstance(val, dict) else {}
            aspect = size.get("aspect") or f.get("default_aspect", "16:9")
            mp = float(size.get("megapixels") or f.get("default_megapixels", 0.4))
            if mode == "aspect_mp":
                binds[f["aspect"]] = ASPECT_LABELS.get(aspect, aspect)
                binds[f["megapixels"]] = mp
            else:
                w, h = size_from(aspect, mp)
                binds[f["width"]] = w
                binds[f["height"]] = h
            continue

        if ftype in _DURATION_TYPES:
            try:
                seconds = float(val)
            except (TypeError, ValueError):
                seconds = float(f.get("default", 5))
            if f.get("snap_frames"):
                binds[f["bind"]] = snap_frames(seconds)
            else:
                binds[f["bind"]] = seconds
            continue

        if ftype == "seed":
            try:
                seed = int(val)
            except (TypeError, ValueError):
                seed = -1
            binds[f["bind"]] = random.randint(0, 2**53 - 1) if seed < 0 else seed
            continue

        if val in (None, "") and not f.get("required"):
            continue
        if f.get("bind"):
            binds[f["bind"]] = val
    return binds


def apply_bindings(workflow: dict, binds: dict[str, Any]) -> dict:
    wf = copy.deepcopy(workflow)
    for compound, value in binds.items():
        if ":" not in compound:
            continue
        node_id, field = compound.split(":", 1)
        node = wf.get(node_id)
        if not isinstance(node, dict):
            raise KeyError(f"工作流里没有节点 {node_id}")
        inputs = node.setdefault("inputs", {})
        inputs[field] = value
    return wf


def card_assets(card: dict) -> dict:
    """能力卡引用到的默认占位资源（图片/视频/音频）。"""
    return card.get("placeholders", {}) or {}

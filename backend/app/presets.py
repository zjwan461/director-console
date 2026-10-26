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

ASPECT_TO_LABEL = {
    "1:1": "1:1 (Square)",
    "2:3": "2:3 (Portrait Photo)",
    "3:2": "3:2 (Photo)",
    "3:4": "3:4 (Portrait Standard)",
    "4:3": "4:3 (Standard)",
    "9:16": "9:16 (Portrait Widescreen)",
    "16:9": "16:9 (Widescreen)",
    "21:9": "21:9 (Ultrawide)",
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


def is_video_card(card: dict) -> bool:
    """能力卡产出的是不是视频。

    图片卡（剧照/角色图）不能单独作为项目里的镜头——镜头是影片的一段，
    必须有动态画面；图片只能当首帧/参考图。
    """
    return str(card.get("output_kind") or "video") != "image"


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
                binds[f["aspect"]] = ASPECT_TO_LABEL.get(aspect, aspect)
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


def _enum_options(object_info: dict, class_type: str, field: str) -> list[str]:
    """兼容两种 object_info 枚举格式：
    旧 [["a","b"], {...}] / 新 ["COMBO", {"options": ["a","b"]}]
    """
    info = object_info.get(class_type)
    if not isinstance(info, dict):
        return []
    inputs = info.get("input") or {}
    for section in ("required", "optional"):
        spec = (inputs.get(section) or {}).get(field)
        if not isinstance(spec, list) or not spec:
            continue
        if isinstance(spec[0], list):
            return [str(x) for x in spec[0]]
        if isinstance(spec[0], str) and len(spec) > 1 and isinstance(spec[1], dict):
            options = spec[1].get("options")
            if isinstance(options, list):
                return [str(x) for x in options]
    return []


MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft")

# 枚举值也可能因节点包版本不同而对不上（例如 RES4LYF 的采样器改名）
# 这里给出安全的降级候选，按优先级取第一个本机存在的
ENUM_FALLBACKS = {
    "sampler_name": ["res_multistep", "euler", "dpmpp_2m", "ddim"],
    "scheduler": ["normal", "simple", "karras"],
    # KJNodes 预览用的小 VAE：本机没有对应文件时用 none（只影响实时预览）
    "tiny_vae": ["none"],
}


# 旧版 RES4LYF 的采样器名在 2025 版被加上了族前缀，且个别名字改了
SAMPLER_ALIASES = {
    "res_2s_ode": "exponential/res_2s",
    "res_2s": "exponential/res_2s",
    "res_3s": "exponential/res_3s",
    "res_2m": "multistep/res_2m",
    "res_3m": "multistep/res_3m",
    "res_multistep": "multistep/res_2m",
}


def _model_key(name: str) -> str:
    """模型名归一化：Windows 上 ComfyUI 用反斜杠报路径，工作流里写的是正斜杠。"""
    return name.replace("\\", "/").lower()


def adapt_workflow_models(workflow: dict, object_info: dict) -> tuple[dict, list[dict]]:
    """提交前按本机 object_info 校正工作流里的枚举值。

    1. 模型文件：分隔符（\\ 与 /）、大小写、路径层级不同时，按文件名找唯一匹配；
    2. sampler / scheduler：节点包版本差异导致名字不存在时降级到安全候选。
    """
    if not object_info:
        return workflow, []

    changes: list[dict] = []
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs")
        if not class_type or not isinstance(inputs, dict):
            continue
        for field, value in list(inputs.items()):
            if not isinstance(value, str):
                continue
            is_model = value.lower().endswith(MODEL_EXTS)
            if not is_model and field not in ENUM_FALLBACKS:
                continue
            options = _enum_options(object_info, class_type, field)
            if not options:
                continue

            if is_model:
                want = _model_key(value)
                # 同一个文件，只是分隔符/大小写不同（Windows 上 ComfyUI 报的是反斜杠）
                same = next((o for o in options if _model_key(o) == want), None)
                if same is not None:
                    if same != value:
                        inputs[field] = same
                        changes.append({"good": value, "actual": same,
                                        "node": class_type, "field": field})
                    continue
                # 真的换了目录层级：按文件名找唯一匹配
                base = want.rsplit("/", 1)[-1]
                matches = [o for o in options if _model_key(o).rsplit("/", 1)[-1] == base]
                if len(matches) == 1:
                    inputs[field] = matches[0]
                    changes.append({"good": value, "actual": matches[0],
                                    "node": class_type, "field": field})
                continue

            if value in options:
                continue

            # RES4LYF 这类节点把采样器按族分组（exponential/res_2s），
            # 老工作流里写的是不带前缀的名字，按「后缀唯一匹配」纠正
            if field == "sampler_name":
                suffix = "/" + value
                hinted = [o for o in options if o.endswith(suffix)]
                if len(hinted) == 1:
                    inputs[field] = hinted[0]
                    changes.append({"good": value, "actual": hinted[0],
                                    "node": class_type, "field": field})
                    continue
                alias = SAMPLER_ALIASES.get(value)
                if alias and alias in options:
                    inputs[field] = alias
                    changes.append({"good": value, "actual": alias,
                                    "node": class_type, "field": field})
                    continue

            for candidate in ENUM_FALLBACKS.get(field, []):
                if candidate in options:
                    inputs[field] = candidate
                    changes.append({"good": value, "actual": candidate,
                                    "node": class_type, "field": field})
                    break
    return workflow, changes


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def sanitize_load_images(workflow: dict, object_info: dict, fallbacks: list[str]) -> list[dict]:
    """把 LoadImage 里“作者机器上才有”的默认图替换成本次上传的图。

    ComfyUI 会校验 prompt 里的每个节点，即使它没连到输出；
    工作流里遗留的参考槽位带着作者的原始文件名（如 zhcnsuggestion_xxx.png），
    在别的机器上就报 custom_validation_failed: Invalid image file。
    """
    if not object_info:
        return []
    info = object_info.get("LoadImage")
    if not isinstance(info, dict):
        return []
    spec = ((info.get("input") or {}).get("required") or {}).get("image")
    if not isinstance(spec, list) or not spec:
        return []
    if isinstance(spec[0], list):
        options = [str(x) for x in spec[0]]
    elif len(spec) > 1 and isinstance(spec[1], dict):
        options = [str(x) for x in (spec[1].get("options") or [])]
    else:
        return []
    if not options:
        return []

    valid = [f for f in fallbacks if f in options]
    if not valid:
        return []

    changes: list[dict] = []
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        inputs = node.get("inputs") or {}
        image = inputs.get("image")
        if isinstance(image, str) and image not in options:
            inputs["image"] = valid[0]
            changes.append({"good": image, "actual": valid[0],
                            "node": "LoadImage", "field": "image"})
    return changes


def apply_bindings(workflow: dict, binds: dict[str, Any]) -> dict:
    # API 格式 JSON 根上带 _api_config 等元数据，ComfyUI 会把它当成节点校验失败
    wf = {
        key: value
        for key, value in copy.deepcopy(workflow).items()
        if isinstance(value, dict) and "class_type" in value
    }
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

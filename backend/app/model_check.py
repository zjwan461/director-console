"""能力卡模型检查：对照 ComfyUI /object_info 判断依赖模型是否存在。"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .comfy import ComfyError, make_client
from .config import settings
from .presets import load_cards, load_workflow

MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft")

FIELD_CATEGORY = {
    "ckpt_name": "checkpoints",
    "unet_name": "diffusion_models",
    "clip_name": "text_encoders",
    "clip_name1": "text_encoders",
    "clip_name2": "text_encoders",
    "clip_name3": "text_encoders",
    "vae_name": "vae",
    "audio_vae": "vae",
    "video_vae": "vae",
    "tiny_vae": "vae",
    "lora_name": "loras",
    "control_net_name": "controlnet",
    "style_model_name": "style_models",
    "upscale_model_name": "upscale_models",
    "upscaler_model": "upscale_models",
}

CLASS_OVERRIDE = {
    ("MiniMaxH3LearnedLatentUpscaleT8Advanced", "model_name"): "latent_upscale_models",
    ("MinimaxH3LatentUpscaler3D", "model_name"): "latent_upscale_models",
    ("SeedVR2LoadDiTModel", "model"): "seedvr2",
    ("SeedVR2LoadVAEModel", "model"): "seedvr2",
    ("SenseNovaH3DistilledBridge", "distilled_adapter"): "loras",
    ("ZealmanLLM_ModelLoader", "主模型"): "LLM",
    ("ZealmanLLM_ModelLoader", "视觉投影mmproj"): "LLM",
}


def _norm(name: str) -> str:
    return name.replace("\\", "/").strip().lower()


def _category(class_type: str, field: str) -> str:
    return CLASS_OVERRIDE.get((class_type, field)) or FIELD_CATEGORY.get(field, "models")


def collect_required(workflow: dict) -> list[dict]:
    found: dict[tuple[str, str], dict] = {}
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        for field, value in (node.get("inputs") or {}).items():
            if not isinstance(value, str):
                continue
            if not value.lower().endswith(MODEL_EXTS):
                continue
            category = _category(class_type, field)
            found[(category, value)] = {
                "file": value,
                "category": category,
                "field": field,
                "node": class_type,
            }
    return list(found.values())


def _available(object_info: dict) -> tuple[set[str], set[str]]:
    full: set[str] = set()
    base: set[str] = set()
    for info in object_info.values():
        if not isinstance(info, dict):
            continue
        inputs = info.get("input") or {}
        for section in ("required", "optional"):
            for spec in (inputs.get(section) or {}).values():
                if isinstance(spec, list) and spec and isinstance(spec[0], list):
                    for value in spec[0]:
                        if isinstance(value, str) and value.lower().endswith(MODEL_EXTS):
                            full.add(_norm(value))
                            base.add(_norm(Path(value).name))
    return full, base


def _command(category: str, filename: str) -> str:
    root = str(settings.get("models.comfy_root", "ComfyUI") or "ComfyUI").rstrip("/")
    base = str(settings.get("models.download_base", "") or "").rstrip("/")
    url = f"{base}/{quote(category)}/{quote(filename)}" if base else "<下载地址>"
    return f'wget -c "{url}" -O "{root}/models/{category}/{filename}"'


_INFO_CACHE: dict[str, tuple[float, dict]] = {}


async def _object_info() -> dict:
    url = settings.base_url
    now = time.time()
    hit = _INFO_CACHE.get(url)
    if hit and now - hit[0] < 60:
        return hit[1]
    data = await make_client().object_info()
    _INFO_CACHE[url] = (now, data)
    return data


async def check_models(card_id: str | None = None) -> dict:
    cards = [
        c for c in load_cards()
        if c.get("_workflow_exists") and (card_id is None or c.get("id") == card_id)
    ]
    if card_id and not cards:
        raise ValueError("能力卡不存在或缺少工作流文件")

    object_info = await _object_info()
    full, base = _available(object_info)

    results = []
    for card in cards:
        workflow = load_workflow(card["workflow"])
        models = []
        for item in sorted(collect_required(workflow), key=lambda x: x["file"].lower()):
            name = item["file"]
            exists = _norm(name) in full or _norm(Path(name).name) in base
            models.append({
                **item,
                "exists": exists,
                "command": "" if exists else _command(item["category"], name),
                "search_url": "https://huggingface.co/models?search=" + quote(Path(name).stem),
            })
        missing = [m for m in models if not m["exists"]]
        results.append({
            "id": card["id"],
            "name": card["name"],
            "models": models,
            "total": len(models),
            "missing_count": len(missing),
        })

    return {
        "cards": results,
        "summary": {
            "cards": len(results),
            "models": sum(c["total"] for c in results),
            "missing": sum(c["missing_count"] for c in results),
        },
        "comfy": {"base_url": settings.base_url},
    }

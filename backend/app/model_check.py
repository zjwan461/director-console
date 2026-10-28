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
    "tiny_vae": "vae_approx",
    "lora_name": "loras",
    "control_net_name": "controlnet",
    "style_model_name": "style_models",
    "upscale_model_name": "upscale_models",
    # SelfLiftH3Sampler 的 upscaler_model 读的是 latent_upscale_models（不是 upscale_models）
    "upscaler_model": "latent_upscale_models",
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


_INV_CACHE: dict[tuple[str, str], tuple[float, set[str]]] = {}


async def _folder_files(category: str) -> set[str]:
    """列某个已注册目录下的文件（带 60s 缓存）。

    有些自定义节点（如 SeedVR2）把文件名当自由字符串，object_info 里没有枚举，
    只看 object_info 会误判“缺失”，所以按目录补一层。
    """
    url = settings.base_url
    key = (url, category)
    now = time.time()
    hit = _INV_CACHE.get(key)
    if hit and now - hit[0] < 60:
        return hit[1]
    names: set[str] = set()
    try:
        # 目录名大小写可能和节点注册的不一致（SeedVR2 注册 models/SEEDVR2，
        # LLM 甚至同时注册了 llm 和 LLM 两份，只有大写的带 .gguf 扩展名）
        registered = await _registered_folders()
        candidates = [category]
        candidates += [c for c in registered if c.lower() == category.lower() and c != category]
        for candidate in candidates:
            for item in await make_client().model_files(candidate):
                names.add(str(item.get("name") if isinstance(item, dict) else item))
            if names:
                break
    except Exception:
        names = set()
    _INV_CACHE[key] = (now, names)
    return names


async def _inventory_files(categories: set[str]) -> tuple[set[str], set[str]]:
    full: set[str] = set()
    base: set[str] = set()
    for category in sorted(categories):
        for name in await _folder_files(category):
            full.add(_norm(f"{category}/{name}"))
            base.add(_norm(Path(name).name))
    return full, base


def _spec_options(spec) -> list[str]:
    """兼容两种 object_info 枚举格式：

    旧: [["a.safetensors", "b.safetensors"], {...}]
    新: ["COMBO", {"options": ["a.safetensors", ...]}]
    """
    if not isinstance(spec, list) or not spec:
        return []
    if isinstance(spec[0], list):
        return [str(x) for x in spec[0]]
    if isinstance(spec[0], str) and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options")
        if isinstance(options, list):
            return [str(x) for x in options]
    return []


def _available(object_info: dict) -> tuple[set[str], set[str]]:
    full: set[str] = set()
    base: set[str] = set()
    for info in object_info.values():
        if not isinstance(info, dict):
            continue
        inputs = info.get("input") or {}
        for section in ("required", "optional"):
            for spec in (inputs.get(section) or {}).values():
                for value in _spec_options(spec):
                    if value.lower().endswith(MODEL_EXTS):
                        full.add(_norm(value))
                        base.add(_norm(Path(value).name))
    return full, base


def _mirror(url: str) -> str:
    """HF 直连在国内基本跑不动：按 config 里的 models.hf_mirror 换成镜像前缀。"""
    mirror = str(settings.get("models.hf_mirror", "") or "").rstrip("/")
    if not mirror or not url:
        return url
    for host in ("https://huggingface.co", "http://huggingface.co"):
        if url.startswith(host):
            return mirror + url[len(host):]
    return url


def _command(category: str, filename: str, url: str = "") -> str:
    root = str(settings.get("models.comfy_root", "") or "").rstrip("/")
    if not url:
        base = str(settings.get("models.download_base", "") or "").rstrip("/")
        url = f"{base}/{quote(category)}/{quote(filename)}" if base else "<下载地址>"
    url = _mirror(url)
    limit = str(settings.get("models.limit_rate", "50m") or "")
    rate = f" --limit-rate {limit}" if limit else ""
    target = f"{root}/models/{category}/{filename}" if root else f"models/{category}/{filename}"
    # --create-dirs：工作流里的相对路径可能带子目录（minimax/、Zimage/），
    # 目标目录不存在时 curl 会直接失败
    return f'curl -L -C -{rate} --create-dirs "{url}" -o "{target}"'


_INFO_CACHE: dict[str, tuple[float, dict]] = {}
_FOLDER_CACHE: dict[str, tuple[float, set[str]]] = {}


async def _registered_folders() -> set[str]:
    """ComfyUI 已注册的模型目录（自定义节点会在 import 时注册自己的目录）。"""
    url = settings.base_url
    now = time.time()
    hit = _FOLDER_CACHE.get(url)
    if hit and now - hit[0] < 60:
        return hit[1]
    try:
        folders = {str(f.get("name")) for f in await make_client().model_folders() if isinstance(f, dict)}
    except Exception:
        folders = set()
    _FOLDER_CACHE[url] = (now, folders)
    return folders


async def _object_info() -> dict:
    url = settings.base_url
    now = time.time()
    hit = _INFO_CACHE.get(url)
    if hit and now - hit[0] < 60:
        return hit[1]
    data = await make_client().object_info()
    _INFO_CACHE[url] = (now, data)
    return data


async def check_models(card_id: str | None = None, source: str = "live") -> dict:
    cards = [
        c for c in load_cards()
        if c.get("_workflow_exists") and (card_id is None or c.get("id") == card_id)
    ]
    if card_id and not cards:
        raise ValueError("能力卡不存在或缺少工作流文件")

    from .model_sources import load_sources

    sources = load_sources()

    inv_full: set[str] = set()
    inv_base: set[str] = set()

    if source == "snapshot":
        from .model_inventory import load_snapshot

        snapshot = load_snapshot()
        if not snapshot:
            raise ValueError("还没有保存过模型清单快照，请先连接云端 ComfyUI 保存一份")
        full = {_norm(f) for f in snapshot.get("files") or []}
        base = {_norm(Path(f).name) for f in full}
        comfy = {
            "base_url": snapshot.get("base_url", ""),
            "source": "snapshot",
            "fetched_at": snapshot.get("fetched_at"),
        }
    else:
        object_info = await _object_info()
        full, base = _available(object_info)
        categories: set[str] = set()
        for card in cards:
            for item in collect_required(load_workflow(card["workflow"])):
                categories.add(str(item.get("category") or ""))
        inv_full, inv_base = await _inventory_files({c for c in categories if c})
        full |= inv_full
        base |= inv_base
        comfy = {"base_url": settings.base_url, "source": "live"}

    node_classes = set(object_info) if source != "snapshot" else set()
    folders = await _registered_folders() if source != "snapshot" else set()

    results = []
    for card in cards:
        workflow = load_workflow(card["workflow"])
        models = []
        for item in sorted(collect_required(workflow), key=lambda x: x["file"].lower()):
            name = item["file"]
            key_full = _norm(name)
            key_base = _norm(Path(name).name)
            # 目录已注册时以「目录里真实存在的文件」为准：
            # SeedVR2 这类节点的枚举是“可下载清单”，文件没下也会出现在 options 里
            if source != "snapshot" and folders and item["category"] in folders:
                exists = key_full in inv_full or key_base in inv_base
            else:
                exists = key_full in full or key_base in base
            entry = sources.get(_norm(name)) or {}
            link = str(entry.get("url") or "")
            # collect_required 里的 node 存的就是 class_type
            class_type = str(item.get("node") or "")
            if exists:
                reason = ""
            elif source == "snapshot":
                reason = "missing"
            elif class_type and node_classes and class_type not in node_classes:
                # 节点没装：它注册的模型目录也不会存在，文件就算下好了也看不到
                reason = "node"
            elif folders and item["category"] not in folders:
                reason = "folder"
            else:
                reason = "missing"
            models.append({
                **item,
                "exists": exists,
                "class_type": class_type,
                "reason": reason,
                "command": "" if exists else _command(item["category"], name, link),
                "url": link,
                "source": "workflow" if link else "none",
                "search_url": "https://huggingface.co/models?search=" + quote(Path(name).stem),
                "search": {
                    "huggingface": "https://huggingface.co/models?search=" + quote(Path(name).stem),
                    "modelscope": "https://modelscope.cn/models?name=" + quote(Path(name).stem),
                    "civitai": "https://civitai.com/search/models?query=" + quote(Path(name).stem),
                },
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
        "comfy": comfy,
    }

"""模型清单快照：优先用 ComfyUI 的 /models 接口，退化为 /object_info。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import settings
from .model_check import _available, _norm

SNAPSHOT_PATH = Path(settings.paths["data"]) / "model-inventory.json"


async def fetch_inventory() -> dict:
    from .comfy import make_client

    client = make_client()
    folders: dict[str, list[str]] = {}
    source = ""

    try:
        names = await client.model_folders()
        for name in names:
            if not isinstance(name, str):
                continue
            try:
                files = await client.model_files(name)
            except Exception:
                continue
            cleaned = sorted({_norm(f) for f in files if isinstance(f, str)})
            if cleaned:
                folders[name] = cleaned
        if folders:
            source = "models"
    except Exception:
        folders = {}

    if not folders:
        info = await client.object_info()
        full, _ = _available(info)
        folders = {"all": sorted(full)}
        source = "object_info"

    files = sorted({f for group in folders.values() for f in group})
    return {
        "base_url": settings.base_url,
        "fetched_at": time.time(),
        "source": source,
        "file_count": len(files),
        "folders": folders,
        "files": files,
    }


def save_snapshot(inventory: dict) -> dict:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return inventory


def load_snapshot() -> dict | None:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None

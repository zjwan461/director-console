"""从 UI 工作流的 properties.models 里提取模型下载地址。"""
from __future__ import annotations

import json
from pathlib import Path

from .config import settings

SOURCES_PATH = Path(settings.paths["data"]) / "model-sources.json"


def _norm(name: str) -> str:
    return name.replace("\\", "/").strip().lower()


def load_sources() -> dict:
    """合并：随仓库发版的 content 映射 + 运行时从 ComfyUI 同步的 data 映射。"""
    merged: dict = {}
    bundled = Path(settings.paths["content"]) / "model-sources.json"
    for path in (bundled, SOURCES_PATH):
        if not path.exists():
            continue
        try:
            merged.update(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return merged


def save_sources(data: dict) -> None:
    SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCES_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def extract_from_workflow(obj: dict) -> list[dict]:
    """遍历 UI workflow 的节点，收集 properties.models。"""
    found: list[dict] = []

    def take(models) -> None:
        if not isinstance(models, list):
            return
        for item in models:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or ""
            url = item.get("url") or ""
            if not name:
                continue
            found.append({
                "name": name,
                "url": url,
                "directory": item.get("directory") or item.get("save_path") or "",
                "hash": item.get("hash") or "",
            })

    take(obj.get("models"))
    for node in obj.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        props = node.get("properties") or {}
        take(props.get("models"))
        take(props.get("Models"))
    return found


def merge_sources(workflows: list[dict]) -> dict:
    sources = load_sources()
    before = len(sources)
    added = 0
    for workflow in workflows:
        for item in extract_from_workflow(workflow):
            key = _norm(item["name"])
            if item["url"]:
                sources[key] = {
                    "name": item["name"],
                    "url": item["url"],
                    "directory": item["directory"],
                    "hash": item["hash"],
                }
                added += 1
    save_sources(sources)
    return {"before": before, "after": len(sources), "updated": added}

"""从 UI 工作流的 properties.models 里提取模型下载地址。"""
from __future__ import annotations

import json
from pathlib import Path

from .config import settings

SOURCES_PATH = Path(settings.paths["data"]) / "model-sources.json"


def _norm(name: str) -> str:
    return name.replace("\\", "/").strip().lower()


def load_sources() -> dict:
    """合并三层：随包 manifest（最低） < content 映射 < 运行时 data 映射。"""
    merged: dict = {}

    manifest_path = Path(settings.paths["content"]) / "model-manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for row in manifest.get("models") or []:
                if isinstance(row, dict) and row.get("url"):
                    merged[_norm(row["file"])] = {
                        "name": row["file"],
                        "url": row["url"],
                        "directory": row.get("category", ""),
                        "hash": "",
                    }
        except Exception:
            pass

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

def _load_data() -> dict:
    if not SOURCES_PATH.exists():
        return {}
    try:
        return json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def upsert_source(name: str, url: str, directory: str = "") -> dict:
    """写入手工映射（data 层，不覆盖随包 content 映射）。url 为空表示删除。"""
    data = _load_data()
    key = _norm(name)
    if url:
        data[key] = {"name": name, "url": url, "directory": directory, "hash": ""}
    else:
        data.pop(key, None)
    save_sources(data)
    return {"count": len(data)}

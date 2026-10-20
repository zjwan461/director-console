"""导演台全局配置：读取项目根 config.yaml，提供默认值与路径。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"
LOCAL_CONFIG_PATH = ROOT / "config.local.yaml"

DEFAULTS: dict[str, Any] = {
    "app": {"host": "127.0.0.1", "port": 6006},
    "comfy": {
        "mode": "local",  # local | ssh | external | mock
        "base_url": "http://127.0.0.1:8188",
        "timeout": 30,
        "local": {
            "workdir": "D:/ComfyUI",
            "python": "python",
            "args": ["main.py", "--listen", "127.0.0.1", "--port", "8188"],
            "env": {},
        },
        "ssh": {
            "host": "",
            "port": 22,
            "user": "root",
            "start": "bash /root/ComfyUI/start.sh",
            "stop": "pkill -f 'python.*main.py'",
            "status": "pgrep -f 'python.*main.py' | head -n1",
            "log": "tail -n 200 /root/ComfyUI/comfyui.log",
        },
    },
    "ai": {
        "base_url": "https://www.autodl.art/api/v1",
        "api_key": "",
        "model": "",
    },
    "ui": {"advanced_panel": "", "comfy_web": ""},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Settings:
    raw: dict = field(default_factory=dict)

    _mtime: tuple = (0.0, 0.0)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        data: dict = {}
        mtime = 0.0
        local_mtime = 0.0
        if CONFIG_PATH.exists():
            mtime = CONFIG_PATH.stat().st_mtime
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        # 本地私有覆盖（不进 git）：放 api_key 之类的敏感项
        if LOCAL_CONFIG_PATH.exists():
            local_mtime = LOCAL_CONFIG_PATH.stat().st_mtime
            local_data = yaml.safe_load(LOCAL_CONFIG_PATH.read_text(encoding="utf-8")) or {}
            data = _deep_merge(data, local_data)
        self.raw = _deep_merge(DEFAULTS, data)
        self.raw.setdefault("paths", {})
        self.raw["paths"] = {
            "root": str(ROOT),
            "data": str(ROOT / "data"),
            "uploads": str(ROOT / "data" / "uploads"),
            "outputs": str(ROOT / "data" / "outputs"),
            "workflows": str(ROOT / "workflows"),
            "presets": str(ROOT / "presets"),
            "content": str(ROOT / "content"),
            "web_dist": str(ROOT / "web" / "dist"),
        }
        for key in ("data", "uploads", "outputs"):
            Path(self.raw["paths"][key]).mkdir(parents=True, exist_ok=True)
        self._mtime = (mtime, local_mtime)

    def refresh_if_changed(self) -> bool:
        """config.yaml 被外部编辑后，无需重启即可生效（返回是否重载）。"""
        try:
            mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0.0
            local_mtime = LOCAL_CONFIG_PATH.stat().st_mtime if LOCAL_CONFIG_PATH.exists() else 0.0
        except OSError:
            return False
        if (mtime, local_mtime) == self._mtime:
            return False
        self.reload()
        return True

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.raw
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    @property
    def paths(self) -> dict[str, str]:
        return self.raw["paths"]

    @property
    def comfy_mode(self) -> str:
        return str(self.get("comfy.mode", "local")).lower()

    @property
    def base_url(self) -> str:
        return str(self.get("comfy.base_url", "http://127.0.0.1:8188")).rstrip("/")


settings = Settings()

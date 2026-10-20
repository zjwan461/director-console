"""ComfyUI HTTP 客户端（含 mock 模式，便于没有显卡时跑通链路）。"""
from __future__ import annotations

import asyncio
import base64
import os
import random
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import settings


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None, token: str | None = None) -> None:
        self.base_url = (base_url or settings.base_url).rstrip("/")
        self.timeout = float(timeout or settings.get("comfy.timeout", 30))
        self.client_id = uuid.uuid4().hex
        effective_token = token if token is not None else str(settings.get("comfy.token", "") or "")
        self.headers = auth_headers(effective_token)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = {**self.headers, **(kwargs.pop("headers", {}) or {})}
        trust_env = bool(settings.get("comfy.trust_env", False))
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=headers, trust_env=trust_env) as client:
                resp = await client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ComfyError(f"连不上 ComfyUI（{self.base_url}）：{exc}") from exc
        if resp.status_code in (401, 403):
            raise ComfyError("ComfyUI 拒绝访问（401/403），请检查访问令牌")
        if resp.status_code >= 400:
            raise ComfyError(f"ComfyUI 返回 {resp.status_code}：{resp.text[:300]}")
        return resp

    # ---------- 只读 ----------
    async def stats(self) -> dict:
        return (await self._request("GET", "/system_stats")).json()

    async def queue(self) -> dict:
        return (await self._request("GET", "/queue")).json()

    async def history(self, prompt_id: str) -> dict:
        return (await self._request("GET", f"/history/{prompt_id}")).json()

    async def object_info(self) -> dict:
        return (await self._request("GET", "/object_info")).json()

    async def model_folders(self) -> list[str]:
        return (await self._request("GET", "/models")).json()

    async def model_files(self, folder: str) -> list[str]:
        return (await self._request("GET", f"/models/{folder}")).json()

    async def health(self) -> dict:
        started = time.perf_counter()
        try:
            data = await self.stats()
            return {
                "ok": True,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "system": data.get("system", {}),
                "devices": data.get("devices", []),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---------- 写 ----------
    async def upload(self, filename: str, content: bytes, kind: str = "input", subfolder: str = "") -> dict:
        files = {"image": (filename, content, _guess_mime(filename))}
        data: dict[str, str] = {"overwrite": "true", "type": kind}
        if subfolder:
            data["subfolder"] = subfolder
        resp = await self._request("POST", "/upload/image", files=files, data=data)
        return resp.json()

    async def submit(self, workflow: dict, client_id: str | None = None) -> str:
        payload = {"prompt": workflow, "client_id": client_id or self.client_id}
        resp = await self._request("POST", "/prompt", json=payload)
        data = resp.json()
        if data.get("error"):
            raise ComfyError(f"工作流校验失败：{data['error']}")
        if data.get("node_errors"):
            raise ComfyError(f"节点错误：{data['node_errors']}")
        pid = data.get("prompt_id")
        if not pid:
            raise ComfyError(f"提交后没有拿到 prompt_id：{data}")
        return str(pid)

    async def wait_history(self, prompt_id: str, timeout: float = 3600, interval: float = 1.5) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = await self.history(prompt_id)
            if prompt_id in data:
                entry = data[prompt_id]
                status = entry.get("status", {})
                if status.get("completed") or status.get("status_str") == "success":
                    return entry
                if status.get("status_str") == "error":
                    raise ComfyError(_status_error(status))
            await asyncio.sleep(interval)
        raise ComfyError("等待生成超时")

    async def download(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
        params = {"filename": filename, "type": kind}
        if subfolder:
            params["subfolder"] = subfolder
        resp = await self._request("GET", "/view", params=params)
        return resp.content

    async def interrupt(self) -> None:
        await self._request("POST", "/interrupt")

    async def free(self, unload_models: bool = True) -> None:
        await self._request(
            "POST", "/free", json={"unload_models": unload_models, "free_memory": True}
        )


def _guess_mime(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")


def _status_error(status: dict) -> str:
    messages: list[str] = []
    for item in status.get("messages", []) or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == "execution_error":
            detail = item[1] or {}
            messages.append(
                f"{detail.get('node_type', '节点')}({detail.get('node_id', '?')}): "
                f"{detail.get('exception_message', '执行失败')}"
            )
    return "；".join(messages) or "ComfyUI 执行失败"


class MockComfy(ComfyClient):
    """没有 ComfyUI 时用：写一个占位视频/图片，把整条链路跑通。"""

    def __init__(self) -> None:
        super().__init__()
        self._jobs: dict[str, dict] = {}

    async def health(self) -> dict:
        return {"ok": True, "mock": True, "latency_ms": 0,
                "system": {"os": "mock", "comfyui_version": "mock"},
                "devices": [{"name": "MOCK GPU", "vram_total": 24 * 1024**3,
                             "vram_free": 20 * 1024**3}]}

    async def upload(self, filename: str, content: bytes, kind: str = "input", subfolder: str = "") -> dict:
        return {"name": filename, "subfolder": subfolder, "type": kind}

    async def submit(self, workflow: dict, client_id: str | None = None) -> str:
        pid = uuid.uuid4().hex
        self._jobs[pid] = {"t": time.time(), "workflow": workflow}
        return pid

    async def wait_history(self, prompt_id: str, timeout: float = 3600, interval: float = 1.5) -> dict:
        started = self._jobs.get(prompt_id, {}).get("t", time.time())
        while time.time() - started < 3:
            await asyncio.sleep(0.3)
        return {
            "prompt": [],
            "outputs": {
                "9": {
                    "gifs": [{"filename": "mock_output.mp4", "subfolder": "mock", "type": "output"}]
                }
            },
            "status": {"completed": True, "status_str": "success"},
        }

    async def download(self, filename: str, subfolder: str = "", kind: str = "output") -> bytes:
        # 最小可播放的 mp4 不好手搓，给一段可识别的文本占位，前端会按“模拟产物”提示
        return b"MOCK_COMFY_OUTPUT\n" + filename.encode()

    async def object_info(self) -> dict:
        raise ComfyError("模拟模式没有真实模型清单，请先在「ComfyUI 连接」里配置真实地址")

    async def interrupt(self) -> None:
        return None

    async def free(self, unload_models: bool = True) -> None:
        return None


def make_client() -> ComfyClient:
    if settings.comfy_mode == "mock":
        return MockComfy()
    return ComfyClient()


def auth_headers(token: str) -> dict[str, str]:
    """支持三种写法：Bearer xxx / Basic xxx / user:password，裸 token 默认 Bearer。"""
    token = (token or "").strip()
    if not token:
        return {}
    lowered = token.lower()
    if lowered.startswith("bearer ") or lowered.startswith("basic "):
        return {"Authorization": token}
    if ":" in token:
        raw = base64.b64encode(token.encode()).decode()
        return {"Authorization": f"Basic {raw}"}
    return {"Authorization": f"Bearer {token}"}


async def probe(base_url: str, token: str = "", timeout: float = 8.0) -> dict:
    """页面上的「测试连接」：不落库，直接打对方的 /system_stats。"""
    client = ComfyClient(base_url=base_url, timeout=timeout, token=token)
    return await client.health()

"""语音转写：OpenAI 兼容的 /audio/transcriptions（阿里云百炼 qwen3-asr-flash 等）。"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

from . import ffmpeg
from .config import settings


def config() -> dict:
    return {
        "base_url": str(
            settings.get("asr.base_url", "")
            or settings.get("tts.base_url", "")
            or settings.get("ai.base_url", "")
        ).rstrip("/"),
        "api_key": str(settings.get("asr.api_key", "") or settings.get("ai.api_key", "")),
        "model": str(settings.get("asr.model", "") or "qwen-audio-3.0-asr-flash"),
        "proxy": str(settings.get("asr.proxy", "") or settings.get("ai.proxy", "") or ""),
    }


def available() -> bool:
    cfg = config()
    return bool(cfg["base_url"] and cfg["api_key"] and cfg["model"])


def _host(base: str) -> str:
    """从任意 base（含 /compatible-mode/v1 或 /api/v1）取出主机名。"""
    base = (base or "").rstrip("/")
    for suffix in ("/compatible-mode/v1", "/api/v1"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


async def transcribe(path: Path) -> str:
    """阿里云百炼 multimodal-generation：input_audio 传 data URI。"""
    cfg = config()
    host = _host(cfg["base_url"])
    if not host or not cfg["api_key"]:
        raise ValueError("还没有配置 ASR（语音转写）")

    import base64
    import tempfile

    # 视频/压缩音频先转成 16k 单声道 wav，ASR 只吃这种规格
    source = path
    if path.suffix.lower() != ".wav":
        tmp_dir = Path(settings.paths["uploads"]) / "asr"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix=".wav", dir=str(tmp_dir))
        os.close(fd)
        source = Path(name)
        await ffmpeg.to_asr_wav(path, source)

    suffix = "wav"
    data_uri = f"data:audio/{suffix};base64," + base64.b64encode(source.read_bytes()).decode()

    kwargs: dict = {"timeout": 180, "trust_env": False}
    if cfg["proxy"]:
        kwargs["proxy"] = cfg["proxy"]

    url = host + "/api/v1/services/aigc/multimodal-generation/generation"
    payload = {
        "model": cfg["model"],
        "input": {"messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": data_uri}}]}]},
        "parameters": {"format": "wav", "sample_rate": "16000"},
    }
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {cfg['api_key']}",
                     "Content-Type": "application/json",
                     "X-DashScope-SSE": "disable"},
            json=payload,
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"转写失败 {resp.status_code}：{resp.text[:300]}"
            + ("（检查 key 是否属于该工作区）" if resp.status_code == 401 else "")
        )
    body = resp.json()
    for candidate in (
        (body.get("output") or {}).get("sentence", {}).get("text"),
        body.get("sentence", {}).get("text"),
        body.get("text"),
    ):
        if candidate:
            return str(candidate).strip()
    raise RuntimeError("转写没有返回文本：" + str(body)[:300])

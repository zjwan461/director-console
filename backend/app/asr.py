"""语音转写：OpenAI 兼容的 /audio/transcriptions（阿里云百炼 qwen3-asr-flash 等）。"""
from __future__ import annotations

from pathlib import Path

import httpx

from .config import settings


def config() -> dict:
    return {
        "base_url": str(settings.get("asr.base_url", "") or settings.get("ai.base_url", "")).rstrip("/"),
        "api_key": str(settings.get("asr.api_key", "") or settings.get("ai.api_key", "")),
        "model": str(settings.get("asr.model", "") or "qwen-audio-3.0-asr-flash"),
        "proxy": str(settings.get("asr.proxy", "") or settings.get("ai.proxy", "") or ""),
    }


def available() -> bool:
    cfg = config()
    return bool(cfg["base_url"] and cfg["api_key"] and cfg["model"])


async def transcribe(path: Path) -> str:
    cfg = config()
    if not cfg["base_url"] or not cfg["api_key"]:
        raise ValueError("还没有配置 ASR（语音转写）")
    kwargs: dict = {"timeout": 180, "trust_env": False}
    if cfg["proxy"]:
        kwargs["proxy"] = cfg["proxy"]
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    async with httpx.AsyncClient(**kwargs) as client:
        # 1) OpenAI 兼容的 /audio/transcriptions
        with path.open("rb") as fh:
            resp = await client.post(
                cfg["base_url"] + "/audio/transcriptions",
                headers=headers,
                data={"model": cfg["model"], "language": "zh"},
                files={"file": (path.name, fh, "audio/wav")},
            )
        if resp.status_code < 400:
            body = resp.json()
            text = str(body.get("text") or body.get("result") or "").strip()
            if text:
                return text

        # 2) 退回 chat/completions + input_audio（阿里云多模态网关常见）
        import base64

        audio_b64 = base64.b64encode(path.read_bytes()).decode()
        resp2 = await client.post(
            cfg["base_url"] + "/chat/completions",
            headers=headers,
            json={
                "model": cfg["model"],
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "请把这段音频转写成中文文本，只输出文本。"},
                        {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
                    ],
                }],
                "stream": False,
            },
        )
        if resp2.status_code < 400:
            body2 = resp2.json()
            try:
                content = body2["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
                text = str(content or "").strip()
                if text:
                    return text
            except (KeyError, IndexError, TypeError):
                pass

        raise RuntimeError(
            "转写失败：/audio/transcriptions 返回 "
            f"{resp.status_code}，chat/completions 返回 {resp2.status_code}。"
            "请检查 asr.base_url / asr.model（例如 qwen3-asr-flash）是否属于当前工作区"
        )

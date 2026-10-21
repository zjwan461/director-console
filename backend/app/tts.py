"""旁白 TTS：阿里云百炼 qwen-audio-3.0-tts-plus（非流式 HTTP）。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from . import ffmpeg
from .config import settings

DEFAULT_FALLBACK = {
    "provider": "aliyun-bailian",
    "base_url": "",
    "api_key": "",
    "proxy": "",
    "model": "qwen-audio-3.0-tts-plus",
    "voice": "longanlufeng",
    "format": "wav",
    "sample_rate": 24000,
}

VOICES = {
    "qwen-audio-3.0-tts-plus": [
        {"id": "longanlufeng", "name": "龙安路风（男，明亮爽朗，解说）"},
        {"id": "longanlingxin", "name": "龙安灵心（女，温暖有共情）"},
    ],
    "qwen-audio-3.1-tts-flash": [
        {"id": "longanhuan_v3.1", "name": "龙安欢 v3.1（女，多语种）"},
        {"id": "anmingyuan_v3.1", "name": "安明远 v3.1（男，旁白）"},
        {"id": "longsanshu_v3.1", "name": "龙三叔 v3.1（男，沉稳有声书）"},
    ],
}

HINTS = {
    "Model not exist": "model 名在这个工作区不存在，请换 model",
    "url error": "端点不对，检查 Base URL（工作区域名）",
    "[cosyvoice:]Engine error [411]": "音色和 model 不配对（3.0-plus 只能用 longanlufeng / longanlingxin，不带后缀）",
    "InvalidApiKey": "API Key 与 Base URL 不属于同一个工作区",
}


def _cfg(key: str):
    return settings.get(f"tts.{key}", DEFAULT_FALLBACK.get(key, ""))


def _host(base: str) -> str:
    """剥掉 /compatible-mode/v1、/api/v1 等路径，只保留主机名。"""
    base = (base or "").rstrip("/")
    for suffix in ("/compatible-mode/v1", "/api/v1"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def config() -> dict:
    return {
        "provider": str(_cfg("provider") or "aliyun-bailian"),
        "base_url": str(_cfg("base_url") or ""),
        "model": str(_cfg("model") or DEFAULT_FALLBACK["model"]),
        "voice": str(_cfg("voice") or DEFAULT_FALLBACK["voice"]),
        "proxy": str(_cfg("proxy") or settings.get("ai.proxy", "") or ""),
        "format": str(_cfg("format") or "wav"),
        "sample_rate": int(_cfg("sample_rate") or 24000),
        "key_set": bool(str(_cfg("api_key") or "")),
        "key_hint": _mask(str(_cfg("api_key") or "")),
    }


def _mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "…" + key[-4:] if len(key) > 8 else "****"


def _explain(raw: str) -> str:
    for needle, hint in HINTS.items():
        if needle in raw:
            return hint
    return ""


def tempo_for(voice_dur: float, slot: float, pad: float = 0.3) -> float:
    target = max(slot - pad, 0.5)
    return round(min(max(voice_dur / target, 1.0), 1.3), 3)


async def synthesize(text: str, voice: str | None = None, use_cache: bool = True) -> dict:
    cfg = config()
    base = _host(cfg["base_url"])
    key = str(_cfg("api_key") or "")
    if not base:
        raise ValueError("还没有配置 TTS Base URL")
    if not key:
        raise ValueError("还没有配置 TTS API Key")
    text = (text or "").strip()
    if not text:
        raise ValueError("旁白文本为空")

    model = cfg["model"]
    voice = voice or cfg["voice"]
    fmt = cfg["format"]
    rate = cfg["sample_rate"]

    digest = hashlib.sha1(f"{model}|{voice}|{fmt}|{rate}|{text}".encode()).hexdigest()[:20]
    out = Path(settings.paths["uploads"]) / "tts" / f"{digest}.{fmt}"
    if use_cache and out.exists() and out.stat().st_size > 0:
        dur = await ffmpeg.duration_of(out)
        return {"path": str(out), "duration": round(dur, 3), "cached": True}

    url = f"{base}/api/v1/services/audio/tts/SpeechSynthesizer"
    payload = {"model": model,
               "input": {"text": text, "voice": voice, "format": fmt, "sample_rate": rate}}
    proxy = cfg["proxy"].strip()
    kwargs: dict = {"timeout": 120, "trust_env": False}
    if proxy:
        kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**kwargs) as client:
        resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {key}"})
        if resp.status_code >= 400:
            raw = resp.text[:400]
            hint = _explain(raw)
            raise RuntimeError(
                f"TTS 返回 {resp.status_code}：{raw}"
                + (f"（{hint}）" if hint else "")
                + f" [POST {url}]"
            )
        body = resp.json()
        audio_url = ((body.get("output") or {}).get("audio") or {}).get("url")
        if not audio_url:
            raise RuntimeError("TTS 没有返回音频地址：" + json.dumps(body, ensure_ascii=False)[:300])
        audio = await client.get(audio_url)
        if audio.status_code >= 400:
            raise RuntimeError(f"下载 TTS 音频失败：{audio.status_code}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio.content)
    dur = await ffmpeg.duration_of(out)
    return {"path": str(out), "duration": round(dur, 3), "cached": False}

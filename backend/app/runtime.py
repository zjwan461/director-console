"""运行时设置：页面里改的 ComfyUI 地址/令牌落库，并覆盖 config.yaml 的默认值。"""
from __future__ import annotations

from . import store
from .config import settings

MODE_KEY = "comfy.mode"
URL_KEY = "comfy.base_url"
TOKEN_KEY = "comfy.token"

AI_BASE_KEY = "ai.base_url"
AI_KEY_KEY = "ai.api_key"
AI_MODEL_KEY = "ai.model"
AI_PROXY_KEY = "ai.proxy"
AI_VISION_KEY = "ai.vision_model"
AI_REASONING_KEY = "ai.reasoning_mode"

TTS_BASE_KEY = "tts.base_url"
TTS_KEY_KEY = "tts.api_key"
TTS_MODEL_KEY = "tts.model"
TTS_VOICE_KEY = "tts.voice"
TTS_FORMAT_KEY = "tts.format"
TTS_RATE_KEY = "tts.sample_rate"
TTS_PROXY_KEY = "tts.proxy"

ASR_BASE_KEY = "asr.base_url"
ASR_KEY_KEY = "asr.api_key"
ASR_MODEL_KEY = "asr.model"
ASR_PROXY_KEY = "asr.proxy"

VALID_MODES = {"local", "ssh", "external", "mock"}


def apply_runtime_settings() -> None:
    """启动时调用：把库里的覆盖值写回 settings.raw，之后所有代码读到的都是最新值。"""
    stored = store.list_settings()
    comfy = settings.raw.setdefault("comfy", {})
    if stored.get(MODE_KEY) in VALID_MODES:
        comfy["mode"] = stored[MODE_KEY]
    if stored.get(URL_KEY):
        comfy["base_url"] = stored[URL_KEY]
    if stored.get(TOKEN_KEY):
        comfy["token"] = stored[TOKEN_KEY]

    ai = settings.raw.setdefault("ai", {})
    if stored.get(AI_BASE_KEY):
        ai["base_url"] = stored[AI_BASE_KEY]
    if stored.get(AI_KEY_KEY):
        ai["api_key"] = stored[AI_KEY_KEY]
    if stored.get(AI_MODEL_KEY):
        ai["model"] = stored[AI_MODEL_KEY]
    if stored.get(AI_PROXY_KEY):
        ai["proxy"] = stored[AI_PROXY_KEY]
    if stored.get(AI_VISION_KEY):
        ai["vision_model"] = stored[AI_VISION_KEY]
    if stored.get(AI_REASONING_KEY):
        ai["reasoning_mode"] = stored[AI_REASONING_KEY]

    asr = settings.raw.setdefault("asr", {})
    if stored.get(ASR_BASE_KEY):
        asr["base_url"] = stored[ASR_BASE_KEY]
    if stored.get(ASR_KEY_KEY):
        asr["api_key"] = stored[ASR_KEY_KEY]
    if stored.get(ASR_MODEL_KEY):
        asr["model"] = stored[ASR_MODEL_KEY]
    if stored.get(ASR_PROXY_KEY):
        asr["proxy"] = stored[ASR_PROXY_KEY]

    tts = settings.raw.setdefault("tts", {})
    for key, name in ((TTS_BASE_KEY, "base_url"), (TTS_KEY_KEY, "api_key"),
                      (TTS_MODEL_KEY, "model"), (TTS_VOICE_KEY, "voice"),
                      (TTS_FORMAT_KEY, "format"), (TTS_RATE_KEY, "sample_rate"),
                      (TTS_PROXY_KEY, "proxy")):
        if stored.get(key):
            tts[name] = stored[key]


def normalize_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def save_comfy_settings(mode: str, base_url: str, token: str | None = None) -> dict:
    mode = (mode or "").strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"不支持的连接方式：{mode}")
    url = normalize_url(base_url)
    if mode != "mock" and not url:
        raise ValueError("请填写 ComfyUI 地址")
    store.set_setting(MODE_KEY, mode)
    store.set_setting(URL_KEY, url)
    if token is not None:
        store.set_setting(TOKEN_KEY, token.strip())
    apply_runtime_settings()
    return public_comfy_settings()


def reset_comfy_settings() -> dict:
    for key in (MODE_KEY, URL_KEY, TOKEN_KEY):
        store.delete_setting(key)
    # 回到 config.yaml 的值
    from importlib import reload

    from . import config as config_module

    reload(config_module)
    settings.raw = config_module.settings.raw
    apply_runtime_settings()
    return public_comfy_settings()


def mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 8:
        return "****"
    return f"{token[:4]}…{token[-4:]}"


def public_comfy_settings() -> dict:
    token = str(settings.get("comfy.token", "") or "")
    return {
        "mode": settings.comfy_mode,
        "base_url": settings.base_url,
        "token_set": bool(token),
        "token_hint": mask_token(token),
        "managed": settings.comfy_mode in {"local", "ssh"},
        "overridden": bool(store.list_settings().get(URL_KEY)),
    }


def save_ai_settings(base_url: str, api_key: str | None, model: str, proxy: str = "",
                     vision_model: str = "", reasoning_mode: str = "") -> dict:
    from .runtime import normalize_url as _normalize

    url = _normalize(base_url)
    if not url:
        raise ValueError("请填写提示词模型的 Base URL")
    store.set_setting(AI_BASE_KEY, url)
    store.set_setting(AI_MODEL_KEY, (model or "").strip())
    store.set_setting(AI_PROXY_KEY, (proxy or "").strip())
    store.set_setting(AI_VISION_KEY, (vision_model or "").strip())
    if reasoning_mode:
        store.set_setting(AI_REASONING_KEY, reasoning_mode.strip().lower())
    if api_key is not None:
        store.set_setting(AI_KEY_KEY, api_key.strip())
    apply_runtime_settings()
    return public_ai_settings()


def reset_ai_settings() -> dict:
    for key in (AI_BASE_KEY, AI_KEY_KEY, AI_MODEL_KEY, AI_PROXY_KEY, AI_VISION_KEY,
                AI_REASONING_KEY):
        store.delete_setting(key)
    from importlib import reload

    from . import config as config_module

    reload(config_module)
    settings.raw = config_module.settings.raw
    apply_runtime_settings()
    return public_ai_settings()


def public_ai_settings() -> dict:
    key = str(settings.get("ai.api_key", "") or "")
    return {
        "base_url": str(settings.get("ai.base_url", "") or ""),
        "model": str(settings.get("ai.model", "") or ""),
        "proxy": str(settings.get("ai.proxy", "") or ""),
        "vision_model": str(settings.get("ai.vision_model", "") or ""),
        "reasoning_mode": str(settings.get("ai.reasoning_mode", "auto") or "auto"),
        "key_set": bool(key),
        "key_hint": mask_token(key),
        "overridden": bool(store.list_settings().get(AI_BASE_KEY)),
    }


def save_tts_settings(base_url: str, api_key: str | None, model: str,
                      voice: str, fmt: str = "wav", sample_rate: int = 24000,
                      proxy: str = "") -> dict:
    url = normalize_url(base_url)
    if not url:
        raise ValueError("请填写 TTS Base URL")
    store.set_setting(TTS_BASE_KEY, url)
    store.set_setting(TTS_MODEL_KEY, (model or "").strip())
    store.set_setting(TTS_VOICE_KEY, (voice or "").strip())
    store.set_setting(TTS_FORMAT_KEY, (fmt or "wav").strip())
    store.set_setting(TTS_RATE_KEY, str(int(sample_rate or 24000)))
    store.set_setting(TTS_PROXY_KEY, (proxy or "").strip())
    if api_key is not None:
        store.set_setting(TTS_KEY_KEY, api_key.strip())
    apply_runtime_settings()
    from . import tts as tts_module

    return tts_module.config()


def reset_tts_settings() -> dict:
    for key in (TTS_BASE_KEY, TTS_KEY_KEY, TTS_MODEL_KEY, TTS_VOICE_KEY, TTS_FORMAT_KEY, TTS_RATE_KEY, TTS_PROXY_KEY):
        store.delete_setting(key)
    from importlib import reload

    from . import config as config_module

    reload(config_module)
    settings.raw = config_module.settings.raw
    apply_runtime_settings()
    from . import tts as tts_module

    return tts_module.config()


def save_asr_settings(base_url: str, api_key: str | None, model: str, proxy: str = "") -> dict:
    url = normalize_url(base_url)
    if not url:
        raise ValueError("请填写 ASR Base URL")
    store.set_setting(ASR_BASE_KEY, url)
    store.set_setting(ASR_MODEL_KEY, (model or "").strip())
    store.set_setting(ASR_PROXY_KEY, (proxy or "").strip())
    if api_key is not None:
        store.set_setting(ASR_KEY_KEY, api_key.strip())
    apply_runtime_settings()
    from . import asr as asr_module

    return asr_module.config()


def reset_asr_settings() -> dict:
    for key in (ASR_BASE_KEY, ASR_KEY_KEY, ASR_MODEL_KEY, ASR_PROXY_KEY):
        store.delete_setting(key)
    from importlib import reload

    from . import config as config_module

    reload(config_module)
    settings.raw = config_module.settings.raw
    apply_runtime_settings()
    from . import asr as asr_module

    return asr_module.config()

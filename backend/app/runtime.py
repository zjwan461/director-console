"""运行时设置：页面里改的 ComfyUI 地址/令牌落库，并覆盖 config.yaml 的默认值。"""
from __future__ import annotations

from . import store
from .config import settings

MODE_KEY = "comfy.mode"
URL_KEY = "comfy.base_url"
TOKEN_KEY = "comfy.token"

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

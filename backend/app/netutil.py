"""网络小工具：内网地址不该走代理。"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def is_local_host(host: str) -> bool:
    """判断主机是不是内网/回环（这些走代理一定会失败）。"""
    host = (host or "").strip().lower().strip("[]")
    if not host:
        return False
    if host in _LOCAL_HOSTS:
        return True
    if host.endswith((".local", ".localdomain", ".internal", ".lan")):
        return True
    # 没有点的主机名（如 myserver）通常是内网短名
    if "." not in host and ":" not in host:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def proxy_for(url: str, proxy: str) -> str | None:
    """给 httpx 用的代理：内网地址返回 None，其余原样返回。"""
    proxy = (proxy or "").strip()
    if not proxy:
        return None
    try:
        host = urlsplit(url).hostname or ""
    except Exception:
        host = ""
    if is_local_host(host):
        return None
    return proxy


def proxy_note(url: str, proxy: str) -> str:
    """给报错信息用：说明到底走没走代理。"""
    if not (proxy or "").strip():
        return "（未配置代理）"
    return "（走了代理）" if proxy_for(url, proxy) else "（内网地址，已绕过代理）"

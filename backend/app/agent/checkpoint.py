"""持久化 checkpoint：确认点存 SQLite，服务重启后仍可续。

Replaces MemorySaver. 用 AsyncSqliteSaver + aiosqlite，表落在同一个 director.db。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..config import settings
from .graph import build_graph

_saver_cm = None
_saver: AsyncSqliteSaver | None = None
_graph = None
_lock = asyncio.Lock()

# 独立文件：checkpointer 会长期持有连接，和业务库放一起容易 database is locked
DB_PATH = Path(settings.paths["data"]) / "agent_state.db"


async def ensure_graph():
    """按需打开 saver 并编译图（进程内只做一次）。"""
    global _saver_cm, _saver, _graph
    if _graph is not None:
        return _graph
    async with _lock:
        if _graph is not None:
            return _graph
        _saver_cm = AsyncSqliteSaver.from_conn_string(str(DB_PATH))
        _saver = await _saver_cm.__aenter__()
        _graph = build_graph(_saver)
        _graph = _graph
        return _graph


async def shutdown() -> None:
    global _saver_cm, _saver, _graph
    _graph = None
    _saver = None
    if _saver_cm is not None:
        try:
            await _saver_cm.__aexit__(None, None, None)
        except Exception:
            pass
        _saver_cm = None

"""事件总线：给前端 SSE 用。

- 每个 thread 保留最近 N 条事件（供断线重连补发）
- 支持多个订阅者（正常情况下只有一个标签页）
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any

MAX_EVENTS = 300


class EventBus:
    def __init__(self) -> None:
        self._history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=MAX_EVENTS))
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._seq: dict[str, int] = defaultdict(int)

    def publish(self, thread_id: str, event: dict) -> dict:
        self._seq[thread_id] += 1
        payload = {"seq": self._seq[thread_id], "ts": time.time(), **event}
        self._history[thread_id].append(payload)
        for queue in list(self._subs.get(thread_id, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
        return payload

    def subscribe(self, thread_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs[thread_id].add(queue)
        return queue

    def unsubscribe(self, thread_id: str, queue: asyncio.Queue) -> None:
        self._subs.get(thread_id, set()).discard(queue)

    def replay(self, thread_id: str, after_seq: int = 0) -> list[dict]:
        return [e for e in list(self._history.get(thread_id, ())) if e.get("seq", 0) > after_seq]


bus = EventBus()

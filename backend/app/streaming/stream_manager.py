from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator
from typing import Any

CLOSE_SENTINEL = "__stream_closed__"


class StreamManager:
    """Request-scoped SSE queue manager.

    Uses thread-safe queues because planning work can run in a background
    thread while FastAPI consumes the stream from an async event loop.
    """

    def __init__(self) -> None:
        self._queues: dict[str, queue.Queue[Any]] = {}

    def register(self, request_id: str) -> None:
        self._queues.setdefault(request_id, queue.Queue(maxsize=500))

    async def send(self, request_id: str, data: Any) -> None:
        target = self._queues.get(request_id)
        if target is None:
            return
        try:
            target.put_nowait(data)
        except queue.Full:
            # Drop the oldest progress item to keep the stream moving.
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            target.put_nowait(data)

    async def close(self, request_id: str) -> None:
        target = self._queues.get(request_id)
        if target is not None:
            target.put_nowait(CLOSE_SENTINEL)

    async def listen(self, request_id: str, *, heartbeat_seconds: float = 15) -> AsyncIterator[Any]:
        self.register(request_id)
        target = self._queues[request_id]
        try:
            while True:
                try:
                    item = await asyncio.to_thread(target.get, True, heartbeat_seconds)
                except queue.Empty:
                    yield {"type": "heartbeat", "request_id": request_id}
                    continue
                if item == CLOSE_SENTINEL:
                    break
                yield item
        finally:
            self._queues.pop(request_id, None)


stream_manager = StreamManager()

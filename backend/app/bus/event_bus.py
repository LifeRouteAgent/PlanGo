from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any
from app.bus.event import EventType

import loguru

from app.bus.event import Event

EventHandler = Callable[[Event], Any | Awaitable[Any]]


class InMemoryEventBus:
    """Broadcast-only event bus.

    The bus intentionally keeps no planning/business state. It stores only
    subscriber callbacks needed for fan-out.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: EventType | str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        handlers = [
            # 先获取这个 `event` 对应的 `event_type` 的订阅者, 在获取全局匹配的订阅者
            *self._subscribers.get(event.event_type, []),
            *self._subscribers.get("*", []),
        ]
        for handler in list(dict.fromkeys(handlers)):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001
                loguru.logger.exception("event subscriber failed: %s", event.event_type)


event_bus = InMemoryEventBus()


def publish_event_sync(event: Event) -> None:
    """Publish from sync graph nodes without blocking the main flow on errors."""

    target = event_bus
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(target.publish(event))
        except Exception:  # noqa: BLE001
            loguru.logger.exception("event publish failed: %s", event.event_type)
        return
    loop.create_task(target.publish(event))

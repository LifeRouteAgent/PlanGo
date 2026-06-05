from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from app.bus.event import Event

EventHandler = Callable[[Event], Any | Awaitable[Any]]

logger = logging.getLogger(__name__)


class InMemoryEventBus:
    """Broadcast-only event bus.

    The bus intentionally keeps no planning/business state. It stores only
    subscriber callbacks needed for fan-out.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        handlers = [
            *self._subscribers.get(event.event_type, []),
            *self._subscribers.get("*", []),
        ]
        for handler in list(dict.fromkeys(handlers)):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.exception("event subscriber failed: %s", event.event_type)


event_bus = InMemoryEventBus()


def publish_event_sync(event: Event, bus: InMemoryEventBus | None = None) -> None:
    """Publish from sync graph nodes without blocking the main flow on errors."""

    target = bus or event_bus
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(target.publish(event))
        except Exception:  # noqa: BLE001
            logger.exception("event publish failed: %s", event.event_type)
        return
    loop.create_task(target.publish(event))

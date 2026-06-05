from __future__ import annotations

import logging

from app.bus.event import Event
from app.bus.event_bus import InMemoryEventBus, event_bus
from app.bus.subscribers.progress_projector import ProgressProjector
from app.streaming.stream_manager import StreamManager, stream_manager

logger = logging.getLogger(__name__)
_installed = False


class FrontendSubscriber:
    def __init__(self, projector: ProgressProjector, stream_manager: StreamManager) -> None:
        self.projector = projector
        self.stream_manager = stream_manager

    async def handle(self, event: Event) -> None:
        try:
            progress = self.projector.project(event)
            if progress is not None:
                await self.stream_manager.send(
                    request_id=event.request_id,
                    data=progress.model_dump(mode="json"),
                )
        except Exception:  # noqa: BLE001
            logger.exception("frontend progress subscriber failed")


def install_frontend_progress_subscriber(
    bus: InMemoryEventBus | None = None,
    manager: StreamManager | None = None,
) -> FrontendSubscriber:
    global _installed
    target_bus = bus or event_bus
    subscriber = FrontendSubscriber(ProgressProjector(), manager or stream_manager)
    if not _installed:
        target_bus.subscribe("*", subscriber.handle)
        _installed = True
    return subscriber

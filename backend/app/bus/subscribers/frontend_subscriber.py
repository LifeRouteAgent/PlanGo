from __future__ import annotations

import loguru

from app.bus.event import Event
from app.bus.event_bus import event_bus
from app.bus.subscribers.progress_projector import ProgressProjector
from app.streaming.stream_manager import StreamManager, stream_manager

_installed = False


class FrontendSubscriber:
    def __init__(self, stream_manager: StreamManager) -> None:
        self.stream_manager = stream_manager

    async def handle(self, event: Event) -> None:
        try:
            progress = ProgressProjector.project(event)
            if progress is not None:
                await self.stream_manager.send(
                    request_id=event.request_id,
                    data=progress.model_dump(mode="json"),
                )
        except Exception:  # noqa: BLE001
            loguru.logger.exception("frontend progress subscriber failed")


def install_frontend_progress_subscriber() -> None:
    global _installed
    if not _installed:
        target_bus = event_bus
        subscriber = FrontendSubscriber(stream_manager)
        # 匹配所有的订阅者, 不管 event_type 了
        target_bus.subscribe("*", subscriber.handle)
        _installed = True
        loguru.logger.info("frontend subscriber installed")

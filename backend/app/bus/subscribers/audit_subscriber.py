from __future__ import annotations

import logging
from typing import Any

from app.bus.event import Event

logger = logging.getLogger(__name__)


class AuditSubscriber:
    """Audit sink for sanitized internal event summaries."""

    def __init__(self, sink: list[dict[str, Any]] | None = None) -> None:
        self.sink = sink

    async def handle(self, event: Event) -> None:
        summary = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "request_id": event.request_id,
            "run_id": event.run_id,
            "node_name": event.node_name,
            "tool_name": event.tool_name,
            "status": event.status,
            "timestamp": event.timestamp.isoformat(),
            "raw_ref": event.raw_ref,
        }
        if self.sink is not None:
            self.sink.append(summary)
        logger.info("planning_event_audit %s", summary)

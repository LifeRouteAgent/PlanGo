from __future__ import annotations

import time
from typing import Any

from app.memory.write_service import MemoryWriteService
from app.observability.trace_recorder import TraceRecorder, set_trace_context


class MemoryEventProcessor:
    """Processes queued memory events; queue transport remains pluggable."""

    def __init__(self, writer: MemoryWriteService | None = None) -> None:
        self.writer = writer or MemoryWriteService()

    def process(self, event: dict[str, Any]) -> None:
        set_trace_context(
            trace_id=str(event.get("trace_id") or ""),
            run_id=str(event.get("run_id") or ""),
            session_id=str(event.get("session_id") or event.get("user_id") or ""),
        )
        started = time.time()
        try:
            event_type = str(event.get("event_type") or "")
            user_id = str(event.get("user_id") or "default")
            if event_type == "plan_feedback_observed":
                self.writer.observe_plan_feedback(
                    event.get("plan") if isinstance(event.get("plan"), dict) else {},
                    user_id=user_id,
                    stage=str(event.get("stage") or "plan_selected"),
                    feedback=(
                        event.get("feedback") if isinstance(event.get("feedback"), dict) else {}
                    ),
                )
            else:
                self.writer.observe_user_query(
                    str(event.get("query") or ""),
                    user_id=user_id,
                )
            TraceRecorder.record(
                "memory_event_processed",
                {
                    "success": True,
                    "duration_ms": int((time.time() - started) * 1000),
                    "source": "local_async_worker",
                },
            )
        except Exception as exc:  # noqa: BLE001
            TraceRecorder.record(
                "memory_event_process_failed",
                {
                    "success": False,
                    "duration_ms": int((time.time() - started) * 1000),
                    "error": str(exc)[:500],
                },
            )

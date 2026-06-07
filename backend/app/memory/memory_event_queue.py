from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.config import settings
from app.memory.event_processor import MemoryEventProcessor
from app.memory.memory_service import MemoryService
from app.memory.write_service import MemoryWriteService
from app.observability.trace_recorder import record_trace_event


class MemoryEventQueue:
    """Asynchronous memory event queue.

    Planning requests enqueue memory work and return immediately. Kafka is used
    when configured; local development still gets a background worker fallback.
    """

    def __init__(self, memory: MemoryService | None = None) -> None:
        self.memory = memory or MemoryService()

    def publish_user_query(
        self,
        query: str,
        *,
        user_id: str,
        trace_id: str = "",
        run_id: str = "",
        session_id: str = "",
    ) -> None:
        event = {
            "event_type": "user_query_observed",
            "query": query,
            "user_id": user_id,
            "trace_id": trace_id,
            "run_id": run_id,
            "session_id": session_id or user_id,
            "created_at": time.time(),
        }
        record_trace_event(
            "memory_event_enqueued",
            {
                "user_id": user_id,
                "kafka_enabled": settings.kafka_enabled,
                "topic": settings.kafka_memory_topic,
            },
        )
        self._publish_to_kafka(event)
        self._start_local_worker(event)

    def publish_plan_feedback(
        self,
        plan: dict[str, Any],
        *,
        user_id: str,
        stage: str,
        feedback: dict[str, Any] | None = None,
        trace_id: str = "",
        run_id: str = "",
        session_id: str = "",
    ) -> None:
        event = {
            "event_type": "plan_feedback_observed",
            "plan": plan,
            "user_id": user_id,
            "stage": stage,
            "feedback": feedback or {},
            "trace_id": trace_id,
            "run_id": run_id,
            "session_id": session_id or user_id,
            "created_at": time.time(),
        }
        record_trace_event(
            "memory_plan_feedback_enqueued",
            {
                "user_id": user_id,
                "stage": stage,
                "plan_id": plan.get("id") or plan.get("plan_id"),
                "topic": settings.kafka_memory_topic,
            },
        )
        self._publish_to_kafka(event)
        self._start_local_worker(event)

    def _start_local_worker(self, event: dict[str, Any]) -> None:
        worker = threading.Thread(
            target=self._process_locally,
            args=(event,),
            daemon=True,
            name="liferoute-memory-worker",
        )
        worker.start()

    def _publish_to_kafka(self, event: dict[str, Any]) -> None:
        if not settings.kafka_enabled:
            return
        try:
            from kafka import KafkaProducer  # type: ignore[import-not-found]

            producer = KafkaProducer(
                bootstrap_servers=settings.kafka_bootstrap_servers,
                value_serializer=lambda value: json.dumps(
                    value,
                    ensure_ascii=False,
                    default=str,
                ).encode("utf-8"),
                linger_ms=5,
                request_timeout_ms=2500,
                max_block_ms=2500,
            )
            producer.send(settings.kafka_memory_topic, event)
            producer.flush(timeout=3)
            producer.close(timeout=1)
            record_trace_event(
                "memory_event_kafka_published",
                {"topic": settings.kafka_memory_topic, "success": True},
            )
        except Exception as exc:  # noqa: BLE001
            record_trace_event(
                "memory_event_kafka_failed",
                {
                    "topic": settings.kafka_memory_topic,
                    "success": False,
                    "error": str(exc)[:500],
                },
            )

    def _process_locally(self, event: dict[str, Any]) -> None:
        MemoryEventProcessor(MemoryWriteService(self.memory)).process(event)
        """本地后台兜底处理，执行原有 LLM Memory 抽取。"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from app.config import settings
from app.services.memory_service import MemoryService
from app.services.trace_recorder import record_trace_event, set_trace_context


class MemoryEventQueue:
    """异步记忆事件队列。

    设计目标：规划请求只负责投递用户输入事件，不等待 Memory LLM 抽取完成。
    - Kafka 可用时：把事件发送到 `KAFKA_MEMORY_TOPIC`，便于后续接独立消费者。
    - 本地开发/演示：同时启动一个后台线程执行 `MemoryService.observe_user_query`，保证
      不启动 Kafka 时长期画像仍能更新。

    注意：Kafka 发布失败不能影响规划主链路，只记录 trace 后走本地后台兜底。
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
        """投递用户输入记忆事件，并立即返回。"""

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
        worker = threading.Thread(
            target=self._process_locally,
            args=(event,),
            daemon=True,
            name="liferoute-memory-worker",
        )
        worker.start()

    def _publish_to_kafka(self, event: dict[str, Any]) -> None:
        """尝试发送 Kafka；失败只记录，不阻塞规划。"""

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
        """本地后台兜底处理，执行原有 LLM Memory 抽取。"""

        set_trace_context(
            trace_id=str(event.get("trace_id") or ""),
            run_id=str(event.get("run_id") or ""),
            session_id=str(event.get("session_id") or event.get("user_id") or ""),
        )
        started = time.time()
        try:
            self.memory.observe_user_query(
                str(event.get("query") or ""),
                user_id=str(event.get("user_id") or "default"),
            )
            record_trace_event(
                "memory_event_processed",
                {
                    "success": True,
                    "duration_ms": int((time.time() - started) * 1000),
                    "source": "local_async_worker",
                },
            )
        except Exception as exc:  # noqa: BLE001
            record_trace_event(
                "memory_event_process_failed",
                {
                    "success": False,
                    "duration_ms": int((time.time() - started) * 1000),
                    "error": str(exc)[:500],
                },
            )

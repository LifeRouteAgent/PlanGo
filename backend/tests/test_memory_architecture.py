from __future__ import annotations

from typing import Any

from app.memory.event_processor import MemoryEventProcessor
from app.memory.policy import MemoryPolicy
from app.memory.read_service import MemoryReadService
from app.memory.redis_keys import MemoryRedisKeys
from app.memory.vector_memory_store import VectorMemoryRecord
from app.memory.write_service import MemoryWriteService


class FakeVectorStore:
    enabled = True
    available = True
    last_error = None

    def __init__(self) -> None:
        self.memories: list[VectorMemoryRecord] = []
        self.profiles: list[tuple[str, str, dict[str, Any]]] = []

    def upsert_memory(self, record: VectorMemoryRecord) -> bool:
        self.memories.append(record)
        return True

    def upsert_user_profile(
        self, user_id: str, profile_text: str, metadata: dict[str, Any]
    ) -> bool:
        self.profiles.append((user_id, profile_text, metadata))
        return True

    def search_memory(
        self, query: str, *, limit: int = 5, user_id: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            {
                "text": record.text,
                "user_id": record.user_id,
                "metadata": record.metadata,
                "score": 0.9,
            }
            for record in self.memories
            if user_id in (None, record.user_id)
        ][:limit]

    def search_similar_profiles(
        self,
        profile_text: str,
        *,
        limit: int = 5,
        exclude_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {"user_id": user_id, "text": text, "metadata": metadata, "score": 0.88}
            for user_id, text, metadata in self.profiles
            if user_id != exclude_user_id
        ][:limit]

    def profile_clusters(self) -> list[dict[str, Any]]:
        return []

    def clear(self, *, user_id: str | None = None) -> None:
        self.memories.clear()
        self.profiles.clear()


def test_memory_policy_accepts_only_confident_long_term_updates() -> None:
    policy = MemoryPolicy()

    temporary = policy.decide_extracted_profile_update(
        {"should_update_profile": True, "scope": "temporary", "confidence": 0.99}
    )
    accepted = policy.decide_extracted_profile_update(
        {"should_update_profile": True, "scope": "long_term", "confidence": 0.9}
    )
    low_confidence = policy.decide_extracted_profile_update(
        {"should_update_profile": True, "scope": "long_term", "confidence": 0.2}
    )

    assert temporary.should_update_profile is False
    assert accepted.should_update_profile is True
    assert low_confidence.should_update_profile is False
    assert policy.stage_weight("plan_executed") > policy.stage_weight("plan_exported_pdf")


def test_memory_read_write_services_keep_profile_flow(monkeypatch) -> None:
    from app.memory.memory_service import MemoryService

    vector_store = FakeVectorStore()
    memory = MemoryService(vector_store=vector_store)  # type: ignore[arg-type]
    writer = MemoryWriteService(memory)
    reader = MemoryReadService(memory)
    user_id = "memory_arch_user"
    writer.clear(user_id=user_id)
    monkeypatch.setattr(
        "app.memory.memory_service.extract_memory_updates",
        lambda query, user_profile=None: {
            "should_update_profile": True,
            "scope": "long_term",
            "confidence": 0.92,
            "profile_updates": {
                "indoor_preference": True,
                "favorite_categories": ["poi_entertainment"],
            },
            "memory_text": "用户长期偏好室内娱乐。",
            "tags": ["室内", "娱乐"],
        },
    )

    writer.observe_user_query("以后优先室内娱乐", user_id=user_id)
    profile = reader.read_profile(user_id=user_id)

    assert profile["indoor_preference"] is True
    assert "poi_entertainment" in profile["favorite_categories"]
    assert reader.build_memory_context(query="室内娱乐", user_id=user_id)["snippets"]


def test_memory_event_processor_delegates_plan_feedback() -> None:
    from app.memory.memory_service import MemoryService

    vector_store = FakeVectorStore()
    memory = MemoryService(vector_store=vector_store)  # type: ignore[arg-type]
    writer = MemoryWriteService(memory)
    user_id = "memory_event_user"
    writer.clear(user_id=user_id)

    MemoryEventProcessor(writer).process({
        "event_type": "plan_feedback_observed",
        "user_id": user_id,
        "stage": "plan_executed",
        "plan": {
            "id": "p1",
            "title": "KTV plan",
            "items": [{"category": "poi_entertainment", "tags": ["KTV"]}],
        },
        "feedback": {"source": "unit_test"},
    })

    profile = memory.read_profile(user_id=user_id)
    assert profile["favorite_categories"]["poi_entertainment"] == 2.2
    assert vector_store.memories[-1].memory_type == "plan_executed"


def test_memory_redis_keys_are_namespaced_and_ttl_bound() -> None:
    session_key = MemoryRedisKeys.session_context("session/42")
    plan_key = MemoryRedisKeys.plan_state("task 7")
    event_key = MemoryRedisKeys.event_idempotency("evt-1")

    assert session_key.key == "liferoute:memory:session:session_42:context"
    assert session_key.ttl_seconds is not None and session_key.ttl_seconds > 0
    assert plan_key.key == "liferoute:memory:plan_state:task_7"
    assert event_key.key == "liferoute:memory:event:evt-1:seen"


def test_runtime_schema_declares_memory_tables() -> None:
    from scripts.init_runtime_schema import DDL

    ddl = "\n".join(DDL)
    for table_name in (
        "memory_user_profiles",
        "memory_preferences",
        "memory_evidence",
        "memory_events",
        "memory_plan_feedback",
        "memory_session_turns",
        "memory_rejected_plans",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in ddl

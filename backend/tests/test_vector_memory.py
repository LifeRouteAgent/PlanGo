from __future__ import annotations

from typing import Any

from app.services.embedding_service import EmbeddingService
from app.services.memory_service import MemoryService
from app.services.vector_memory_store import VectorMemoryRecord


class FakeVectorStore:
    """测试用向量存储，避免依赖真实 Milvus 服务。"""

    enabled = True
    available = True
    last_error = None

    def __init__(self) -> None:
        self.memories: list[VectorMemoryRecord] = []
        self.profiles: list[tuple[str, str, dict[str, Any]]] = []

    def upsert_memory(self, record: VectorMemoryRecord) -> bool:
        self.memories.append(record)
        return True

    def upsert_user_profile(self, user_id: str, profile_text: str, metadata: dict[str, Any]) -> bool:
        self.profiles.append((user_id, profile_text, metadata))
        return True

    def search_memory(self, query: str, *, limit: int = 5, user_id: str | None = None) -> list[dict[str, Any]]:
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
            {
                "user_id": user_id,
                "text": text,
                "metadata": metadata,
                "score": 0.88,
            }
            for user_id, text, metadata in self.profiles
            if user_id != exclude_user_id
        ][:limit]

    def profile_clusters(self) -> list[dict[str, Any]]:
        return [{"cluster_id": "indoor_low_poi_entertainment", "count": 1}]

    def clear(self, *, user_id: str | None = None) -> None:
        self.memories.clear()
        self.profiles.clear()


def test_embedding_service_fallback_vector_has_fixed_dimension() -> None:
    """本地模型不可用时，EmbeddingService 仍返回固定维度的稳定向量。"""

    service = EmbeddingService(model_path="not-exist-model", dimension=16)
    service._get_model = lambda: (_ for _ in ()).throw(RuntimeError("model unavailable"))  # type: ignore[method-assign]

    vector = service.embed_text("喜欢室内、KTV、低预算")

    assert len(vector) == 16
    assert any(value != 0 for value in vector)


def test_memory_service_writes_file_and_vector_memory() -> None:
    """用户输入和采纳方案应同时沉淀文件记忆与向量记忆。"""

    fake_store = FakeVectorStore()
    memory = MemoryService(vector_store=fake_store)  # type: ignore[arg-type]
    memory.clear(user_id="u1")

    memory.observe_user_query("不要室外了，今天太热，预算200", user_id="u1")
    memory.observe_selected_plan({
        "id": "p1",
        "title": "室内娱乐方案",
        "items": [{"category": "poi_entertainment", "tags": ["KTV", "室内"]}],
        "estimated_budget": 180,
        "total_duration_minutes": 240,
    }, user_id="u1")

    profile = memory.read_profile()
    assert profile["indoor_preference"] is True
    assert "室外" in profile["disliked_keywords"]
    assert fake_store.memories
    assert fake_store.profiles


def test_memory_semantic_search_falls_back_to_vector_results() -> None:
    """semantic_search 优先返回向量命中结果。"""

    fake_store = FakeVectorStore()
    memory = MemoryService(vector_store=fake_store)  # type: ignore[arg-type]
    memory.clear(user_id="u2")
    memory.observe_user_query("喜欢麻将和唱歌", user_id="u2")

    results = memory.semantic_search("唱歌", user_id="u2")

    assert results
    assert "唱歌" in results[0]["text"]

from __future__ import annotations

from typing import Any

from app.memory.memory_service import MemoryService


class MemoryReadService:
    """Read-side facade used by Planning Graph V2 context nodes and debug APIs."""

    def __init__(self, memory: MemoryService | None = None) -> None:
        self.memory = memory or MemoryService()

    def read_profile(self, *, user_id: str = "default") -> dict[str, Any]:
        return self.memory.read_profile(user_id=user_id)

    def build_memory_context(
        self, *, query: str, user_id: str = "default", limit: int = 5
    ) -> dict[str, Any]:
        return self.memory.build_memory_context(query=query, user_id=user_id, limit=limit)

    def similar_user_preferences(
        self,
        profile: dict[str, Any] | None = None,
        *,
        user_id: str = "default",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        return self.memory.similar_user_preference_search(profile, user_id=user_id, limit=limit)

    def profile_payload(self, *, user_id: str = "default") -> dict[str, Any]:
        return self.memory.profile_payload(user_id=user_id)

    def semantic_search(
        self, query: str, *, limit: int = 5, user_id: str = "default"
    ) -> list[dict[str, Any]]:
        return self.memory.semantic_search(query, limit=limit, user_id=user_id)

    def clusters(self) -> list[dict[str, Any]]:
        return self.memory.clusters()

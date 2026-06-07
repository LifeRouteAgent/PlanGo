from __future__ import annotations

from typing import Any

from app.memory.memory_service import MemoryService


class MemoryWriteService:
    """Write-side facade for long-term memory and session behavior events."""

    def __init__(self, memory: MemoryService | None = None) -> None:
        self.memory = memory or MemoryService()

    def observe_user_query(self, query: str, *, user_id: str = "default") -> None:
        self.memory.observe_user_query(query, user_id=user_id)

    def observe_plan_feedback(
        self,
        plan: dict[str, Any],
        *,
        user_id: str = "default",
        stage: str = "plan_selected",
        feedback: dict[str, Any] | None = None,
    ) -> None:
        self.memory.observe_plan_feedback(plan, user_id=user_id, stage=stage, feedback=feedback)

    def observe_selected_plan(self, plan: dict[str, Any], *, user_id: str = "default") -> None:
        self.memory.observe_selected_plan(plan, user_id=user_id)

    def observe_rejected_plan(self, plan_id: str, *, reason: str = "", user_id: str = "default") -> None:
        self.memory.observe_rejected_plan(plan_id, reason=reason, user_id=user_id)

    def observe_revision(self, query: str, parsed_patch: dict[str, Any], *, user_id: str = "default") -> None:
        self.memory.observe_revision(query, parsed_patch, user_id=user_id)

    def clear(self, *, user_id: str | None = None) -> None:
        self.memory.clear(user_id=user_id)

    def rebuild_vector_index(self, *, user_id: str = "default") -> dict[str, Any]:
        return self.memory.rebuild_vector_index(user_id=user_id)

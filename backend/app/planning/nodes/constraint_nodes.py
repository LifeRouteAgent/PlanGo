from __future__ import annotations

from typing import Any

from app.planning.nodes.common import append_trace
from app.planning.services.constraint_service import build_constraints
from app.planning.state import PlanningState


def constraint_builder_node(state: PlanningState) -> dict[str, Any]:
    constraints, recall = build_constraints(
        state.llm_understanding,
        city=state.user_info.city,
        origin=state.user_info.default_origin,
        previous=state.context.current_plan_state.last_constraints_snapshot or {},
        session_preference=state.context.session_preference_profile,
    )
    return {
        "constraints": constraints,
        "recall_plan": recall,
        "debug": append_trace(state, "constraint_builder", "最终约束与逻辑召回计划已生成"),
    }

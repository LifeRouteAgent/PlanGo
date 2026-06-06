from __future__ import annotations

from typing import Any

from app.planning.nodes.common import append_trace, ensure_state
from app.planning.services.routing_service import create_route_plans
from app.planning.state import PlanningState


def plan_editor_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    context = state.context.model_copy(deep=True)
    adjustment = state.llm_understanding.intent.adjustment_type if state.llm_understanding else "rerank"
    target = ["restaurant"] if adjustment in {"replace_slot", "lower_budget"} else list(
        state.constraints.hard_constraints.required_slots
    )
    context.current_plan_state.target_edit_slots = target
    context.current_plan_state.frozen_slots = [
        slot for slot in state.constraints.hard_constraints.required_slots if slot not in target
    ]
    return {
        "context": context,
        "debug": append_trace(state, "plan_editor", f"set edit slots: {','.join(target)}"),
    }


def route_planner_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    plans = state.plans.model_copy(deep=True)
    plans.candidate_plans = create_route_plans(state.candidates.balanced_candidates, state.constraints)
    return {
        "plans": plans,
        "debug": append_trace(state, "route_planner", f"created {len(plans.candidate_plans)} candidate plans"),
    }

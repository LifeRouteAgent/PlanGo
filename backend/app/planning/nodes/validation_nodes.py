from __future__ import annotations

from typing import Any

from app.planning.nodes.common import append_trace, ensure_state
from app.planning.services.availability_service import (
    analyze_failure_reason,
    check_plan_availability,
    relax_constraints_for_failure,
)
from app.planning.services.ranking_service import rank_route_plans
from app.planning.state import PlanningState


def pre_ranker_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    plans = state.plans.model_copy(deep=True)
    kept, ranked = rank_route_plans(
        plans.candidate_plans,
        state.candidates.scored_candidates,
        state.constraints,
        top_n=30,
    )
    plans.candidate_plans = kept
    plans.ranked_plans = ranked
    return {
        "plans": plans,
        "debug": append_trace(
            state, "pre_ranker", f"kept {len(kept)} plans for availability check"
        ),
    }


def availability_checker_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    availability, filtered, warnings = check_plan_availability(
        state.plans.candidate_plans,
        state.candidates.scored_candidates,
    )
    plans = state.plans.model_copy(deep=True)
    plans.availability_results = availability
    plans.candidate_plans = filtered
    debug = append_trace(state, "availability_checker", f"available plans: {len(filtered)}")
    debug.recall_debug["availability_plan_warnings"] = warnings
    debug.recall_debug["pre_availability_plan_count"] = len(state.plans.candidate_plans)
    return {"plans": plans, "debug": debug}


def post_check_filter_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    return {
        "debug": append_trace(
            state, "post_check_filter", f"post-check plan count: {len(state.plans.candidate_plans)}"
        ),
    }


def failure_analyzer_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    reason = analyze_failure_reason(
        state.candidates.raw_candidates,
        state.candidates.balanced_candidates,
        [None] * int(state.debug.recall_debug.get("pre_availability_plan_count") or 0),
        state.plans.candidate_plans,
        state.plans.availability_results,
    )
    debug = append_trace(state, "failure_analyzer", f"failure reason: {reason}")
    debug.recall_debug["failure_reason"] = reason
    iteration = int(debug.recall_debug.get("fallback_iteration") or 0)
    debug.recall_debug["needs_fallback"] = iteration < 2 and len(state.plans.candidate_plans) < 3
    return {"debug": debug}


def fallback_relaxation_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    reason = str(state.debug.recall_debug.get("failure_reason") or "unknown")
    iteration = int(state.debug.recall_debug.get("fallback_iteration") or 0) + 1
    constraints, recall = relax_constraints_for_failure(
        state.constraints, state.recall_plan, reason, iteration
    )
    debug = append_trace(
        state, "fallback_relaxation", f"relaxed constraints: {reason}, iteration {iteration}"
    )
    debug.recall_debug["fallback_iteration"] = iteration
    debug.recall_debug["needs_fallback"] = False
    return {"constraints": constraints, "recall_plan": recall, "debug": debug}


def final_ranker_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    plans = state.plans.model_copy(deep=True)
    kept, ranked = rank_route_plans(
        plans.candidate_plans,
        state.candidates.scored_candidates,
        state.constraints,
        availability=plans.availability_results,
        top_n=3,
    )
    plans.candidate_plans = kept
    plans.ranked_plans = ranked
    return {
        "plans": plans,
        "debug": append_trace(state, "final_ranker", f"final plans: {len(ranked)}"),
    }


def post_check_route(value: PlanningState | dict[str, Any]) -> str:
    state = ensure_state(value)
    return "final_ranker" if len(state.plans.candidate_plans) >= 3 else "failure_analyzer"


def failure_route(value: PlanningState | dict[str, Any]) -> str:
    state = ensure_state(value)
    return (
        "fallback_relaxation" if state.debug.recall_debug.get("needs_fallback") else "final_ranker"
    )

from __future__ import annotations

from typing import Any

from app.graph.nodes.common import append_trace, ensure_state
from app.graph.services.recall_service import collect_candidates, compile_recall_plan
from app.graph.state import PlanningState


def recall_plan_compiler_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    compiled = compile_recall_plan(state.recall_plan, state.constraints, state.context.poi_logical_tag_catalog)
    return {
        "compiled_recall_plan": compiled,
        "debug": append_trace(state, "recall_plan_compiler", f"编译 {len(compiled.queries)} 条安全召回查询"),
    }


def collector_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    candidates = state.candidates.model_copy(deep=True)
    candidates.raw_candidates, candidates.recall_stats = collect_candidates(
        state.compiled_recall_plan, state.constraints
    )
    return {
        "candidates": candidates,
        "debug": append_trace(state, "collector", f"召回 {candidates.recall_stats.total_raw_count} 个安全候选"),
    }

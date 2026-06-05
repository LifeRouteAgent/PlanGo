from __future__ import annotations

from typing import Any

from app.graph.state import DebugState, NodeTrace, PlanningState


def ensure_state(value: PlanningState | dict[str, Any]) -> PlanningState:
    return value if isinstance(value, PlanningState) else PlanningState.model_validate(value)


def append_trace(state: PlanningState, node: str, message: str) -> DebugState:
    debug = state.debug.model_copy(deep=True)
    debug.node_trace.append(NodeTrace(node=node, status="completed", message=message))
    return debug

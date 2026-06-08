from __future__ import annotations


from app.planning.state import DebugState, NodeTrace, PlanningState


def append_trace(state: PlanningState, node: str, message: str) -> DebugState:
    debug = state.debug.model_copy(deep=True)
    debug.node_trace.append(NodeTrace(node=node, status="completed", message=message))
    return debug

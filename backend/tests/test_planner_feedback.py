from __future__ import annotations

from app.graph.graph_builder import run_planning_request


def test_v2_planning_failure_context_stays_internal() -> None:
    state = run_planning_request("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")

    assert state.response.response_payload is not None
    assert "raw_candidates" not in state.response.response_payload
    assert state.debug.node_trace

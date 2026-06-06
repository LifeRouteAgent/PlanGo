from __future__ import annotations

from app.planning.graph_builder import run_planning_request


def test_local_life_v2_smoke_flow_generates_structured_payload() -> None:
    state = run_planning_request("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")

    nodes = [trace.node for trace in state.debug.node_trace]
    assert state.llm_understanding.intent.request_type == "full_itinerary_plan"
    assert "collector" in nodes
    assert "route_planner" in nodes
    assert state.response.response_payload
    assert state.response.response_payload["response_type"] == "plan_cards"

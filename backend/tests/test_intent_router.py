from __future__ import annotations

from app.planning.graph_builder import run_planning_request
from app.planning.state import planning_state_to_legacy


def _node_names(query: str) -> tuple[str, list[str], dict]:
    """测试只关心分支契约，不绑定内部业务文案。"""

    state = run_planning_request(query)
    legacy = planning_state_to_legacy(state)
    return state.llm_understanding.intent.request_type, [trace.node for trace in state.debug.node_trace], legacy


def test_capability_question_skips_planning_nodes() -> None:
    request_type, nodes, legacy = _node_names("你能做什么？")

    assert request_type == "simple_qa"
    assert "simple_response_generator" in nodes
    assert "collector" not in nodes
    assert legacy["need_clarification"] is False


def test_category_recommendation_uses_lightweight_path() -> None:
    request_type, nodes, legacy = _node_names("推荐几个适合朋友聚会的餐厅")

    assert request_type == "single_category_recommend"
    assert "single_category_ranker" in nodes
    assert "route_planner" not in nodes
    assert legacy["need_clarification"] is False


def test_full_trip_plan_runs_route_branch_without_clarification() -> None:
    request_type, nodes, legacy = _node_names("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")

    assert request_type == "full_itinerary_plan"
    assert "route_planner" in nodes
    assert "final_ranker" in nodes
    assert legacy["need_clarification"] is False


def test_vague_plan_uses_defaults_instead_of_clarification() -> None:
    request_type, nodes, legacy = _node_names("周末想出去玩")

    assert request_type == "full_itinerary_plan"
    assert "constraint_builder" in nodes
    assert legacy["need_clarification"] is False

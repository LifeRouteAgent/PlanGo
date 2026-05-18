from __future__ import annotations

import pytest

from app.agents.issue_utils import issue_codes
from app.dag.langgraph_dag_config import life_route_graph
from app.state.plan_state import create_initial_state


@pytest.mark.parametrize(
    "force_flag,expected_error",
    [
        ("force_empty_candidates", "candidate_empty"),
        ("force_restaurant_unavailable", "restaurant_unavailable"),
        ("force_route_timeout", "route_timeout"),
        ("force_duration_exceeded", "total_duration_exceeded"),
    ],
)
def test_verifier_feedback_loop_recovers_after_one_replan(
    force_flag: str,
    expected_error: str,
) -> None:
    """Verifier 失败后应回退 Planner，并在第二轮生成可执行方案。

    这些 force_* 开关只用于测试异常分支：第一轮强制制造失败，
    第二轮关闭失败条件，验证 DAG 反馈循环是否真的生效。
    """

    state = create_initial_state(
        "周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元",
        user_profile={force_flag: True},
        max_replanning_count=2,
    )

    result = life_route_graph.invoke(state)

    assert expected_error not in issue_codes(result["errors"])
    assert result["execution_status"] == "simulated"
    assert result["selected_plan"]["verified"] is True
    assert result["replanning_count"] == 2
    assert any("retry_policy" in log for log in result["logs"])

from __future__ import annotations

from app.agents.issue_utils import make_issue
from app.agents.planner_agent import planner_agent_node
from app.state.plan_state import create_initial_state
from app.tools.poi_schema import POI_RESTAURANT


def test_planner_turns_budget_issue_into_budget_strategy() -> None:
    """Verifier 返回预算超出后，Planner 下一轮应切换到预算优先策略。"""

    state = create_initial_state("朋友聚餐，预算 200")
    state["intent_type"] = "full_trip_plan"
    state["target_categories"] = [POI_RESTAURANT]
    state["constraints"] = {
        "duration_hours": 3,
        "budget": 200,
        "people_count": 2,
        "scenario": "friends",
        "preferences": ["餐厅"],
    }
    state["errors"] = [
        make_issue(
            "budget_exceeded",
            source="verifier",
            target_plan_id="plan_1",
            details={"plan_id": "plan_1", "estimated_budget": 360, "budget": 200},
        )
    ]
    state["replanning_count"] = 1

    patch = planner_agent_node(state)

    assert patch["dag_plan"]["retry_policy"] == "lower_price_level"
    assert patch["dag_plan"]["candidate_strategy"] == "budget_fit_first"

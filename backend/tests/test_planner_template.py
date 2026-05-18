from __future__ import annotations

from app.agents.planner_agent import planner_agent_node
from app.state.plan_state import create_initial_state
from app.tools.poi_schema import POI_ENTERTAINMENT, POI_RESTAURANT


def test_planner_outputs_friends_gathering_template() -> None:
    """朋友聚会类完整规划应输出模板、槽位、时间预算和移动策略。"""

    state = create_initial_state("周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600，别太远")
    state["intent_type"] = "full_trip_plan"
    state["target_categories"] = [POI_RESTAURANT, POI_ENTERTAINMENT]
    state["constraints"] = {
        "scenario": "friends",
        "people_count": 4,
        "preferences": ["餐厅", "休闲娱乐"],
        "duration_hours": 4,
    }

    patch = planner_agent_node(state)
    dag_plan = patch["dag_plan"]

    assert dag_plan["planning_template"] == "friends_gathering"
    assert dag_plan["required_slots"] == [
        "activity_or_entertainment",
        "restaurant",
        "optional_lifestyle",
    ]
    assert dag_plan["time_budget"] == 240
    assert dag_plan["movement_policy"] == "compact_walk_or_taxi"
    assert dag_plan["candidate_strategy"] == "slot_balance"
    assert dag_plan["collector_categories"] == [POI_RESTAURANT, POI_ENTERTAINMENT]


def test_planner_outputs_category_recommendation_template() -> None:
    """单类推荐不应套完整行程模板，只需要类别聚焦策略。"""

    state = create_initial_state("推荐几个适合朋友聚会的餐厅")
    state["intent_type"] = "category_recommend"
    state["target_categories"] = [POI_RESTAURANT]
    state["constraints"] = {"duration_hours": 6}

    patch = planner_agent_node(state)
    dag_plan = patch["dag_plan"]

    assert dag_plan["planning_template"] == "category_recommendation"
    assert dag_plan["required_slots"] == ["restaurant"]
    assert dag_plan["candidate_strategy"] == "category_focus"


def test_planner_replan_route_timeout_switches_to_same_area_strategy() -> None:
    """路线超时回退后，Planner 应收紧为同商圈优先和紧凑槽位策略。"""

    state = create_initial_state("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")
    state["intent_type"] = "full_trip_plan"
    state["target_categories"] = [POI_RESTAURANT, POI_ENTERTAINMENT]
    state["constraints"] = {
        "scenario": "friends",
        "people_count": 2,
        "preferences": ["餐厅", "休闲娱乐"],
        "duration_hours": 4,
    }
    state["replanning_count"] = 1
    state["errors"] = ["route_timeout"]

    patch = planner_agent_node(state)
    dag_plan = patch["dag_plan"]

    assert dag_plan["retry_policy"] == "compact_timeline"
    assert dag_plan["movement_policy"] == "same_business_area_first"
    assert dag_plan["candidate_strategy"] == "compact_slots_same_area_first"

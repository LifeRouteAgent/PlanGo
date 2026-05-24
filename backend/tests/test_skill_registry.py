from __future__ import annotations

from app.agents.planner_agent import planner_agent_node
from app.state.plan_state import create_initial_state
from app.tools.poi_restaurant_recommend import poi_restaurant_recommend_node
from app.tools.poi_schema import POI_ENTERTAINMENT, POI_RESTAURANT
from app.tools.skill_registry import select_skills_for_plan


def test_planner_selects_lifestyle_skill_for_entertainment_gathering() -> None:
    """“打麻将再唱歌”这类娱乐聚会不应默认把四个 Skill 全部启用。"""

    state = create_initial_state("周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算200")
    state["intent_type"] = "full_trip_plan"
    state["target_categories"] = [POI_ENTERTAINMENT]
    state["constraints"] = {
        "duration_hours": 4,
        "budget": 200,
        "people_count": 2,
        "scenario": "friends",
        "preferences": ["麻将", "唱歌"],
        "llm_understanding": {
            "intent_type": "full_trip_plan",
            "target_categories": [POI_ENTERTAINMENT],
            "planning_template": "entertainment_gathering",
            "required_slots": ["entertainment", "optional_entertainment"],
        },
    }

    patch = planner_agent_node(state)
    dag_plan = patch["dag_plan"]

    assert dag_plan["enabled_skills"] == ["poi_lifestyle_recommend"]
    assert dag_plan["parallel_skills"] == dag_plan["enabled_skills"]
    assert dag_plan["collector_categories"] == [POI_ENTERTAINMENT]
    assert dag_plan["slot_sequence"] == ["entertainment", "optional_entertainment"]


def test_category_recommendation_enables_only_target_category_skill() -> None:
    """单类推荐只启用目标类别对应 Skill，避免无关 Skill 消耗候选和上下文。"""

    skills = select_skills_for_plan(
        intent_type="category_recommend",
        categories=[POI_RESTAURANT],
        required_slots=["restaurant"],
        planning_template="category_recommendation",
    )

    assert skills == ["poi_restaurant_recommend"]


def test_disabled_skill_returns_only_skip_log() -> None:
    """Planner 明确禁用某个 Skill 时，该 Skill 不能写 recommended_pois。"""

    state = create_initial_state("推荐一个 KTV")
    state["dag_plan"] = {"enabled_skills": ["poi_lifestyle_recommend"]}
    state["candidate_pois"] = {
        POI_RESTAURANT: [{
            "id": "r1",
            "name": "测试餐厅",
            "category": POI_RESTAURANT,
            "subcategory": "hotpot",
            "lat": 39.9,
            "lon": 116.4,
            "address": "测试地址",
            "rating": 4.7,
            "price_level": "medium",
            "open_status": "open",
            "tags": ["聚餐"],
        }]
    }

    patch = poi_restaurant_recommend_node(state)

    assert "recommended_pois" not in patch
    assert "skipped" in patch["logs"][0]

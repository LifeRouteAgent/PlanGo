from __future__ import annotations

from app.agents.poi_collector import poi_collector_node
from app.state.plan_state import create_initial_state
from app.tools.poi_activity_recommend import poi_activity_recommend_node
from app.tools.poi_lifestyle_recommend import poi_lifestyle_recommend_node
from app.tools.poi_restaurant_recommend import poi_restaurant_recommend_node
from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
)


def test_collector_outputs_unified_poi_fields() -> None:
    """Collector 必须稳定输出统一 POI 基础字段，并允许图片/距离等扩展字段。"""

    state = create_initial_state("周末出去玩", user_profile={"use_database": False})
    state["dag_plan"] = {"collector_categories": [POI_ACTIVITY, POI_RESTAURANT]}

    patch = poi_collector_node(state)
    activity = patch["candidate_pois"][POI_ACTIVITY][0]

    required_fields = {
        "id",
        "name",
        "category",
        "subcategory",
        "lat",
        "lon",
        "address",
        "rating",
        "price_level",
        "open_status",
        "tags",
    }
    assert required_fields.issubset(set(activity))
    assert activity["category"] == POI_ACTIVITY


def test_activity_skill_outputs_scored_recommendations() -> None:
    """活动 Skill 应输出推荐分和本地生活可执行性字段。"""

    state = create_initial_state("周末体验活动", user_profile={"use_database": False})
    state["constraints"] = {
        "duration_hours": 4,
        "budget": 600,
        "people_count": 2,
        "scenario": "friends",
    }
    state["candidate_pois"] = poi_collector_node({
        **state,
        "dag_plan": {"collector_categories": [POI_ACTIVITY]},
    })["candidate_pois"]

    patch = poi_activity_recommend_node(state)
    item = patch["recommended_pois"]["activity"][0]

    assert item["category"] == POI_ACTIVITY
    assert item["score"] > item["rating"]
    assert item["reason"]
    assert item["estimated_duration_minutes"] > 0
    assert item["reservation_required"] is True
    assert item["crowd_risk"] in {"low", "medium", "high"}
    assert item["budget_fit"] in {"good", "tight", "over_budget", "unknown"}
    assert 0 <= item["scene_fit"] <= 1
    assert item["distance_sensitive"] is True
    assert "reservation_required" in item["risk_flags"]


def test_restaurant_skill_considers_budget_and_queue_risk() -> None:
    """餐厅 Skill 应输出预算、场景、预约和排队风险字段。"""

    state = create_initial_state(
        "周末和朋友吃饭，预算 200 元", user_profile={"use_database": False}
    )
    state["constraints"] = {
        "duration_hours": 3,
        "budget": 200,
        "people_count": 2,
        "scenario": "friends",
    }
    state["candidate_pois"] = poi_collector_node({
        **state,
        "dag_plan": {"collector_categories": [POI_RESTAURANT]},
    })["candidate_pois"]

    patch = poi_restaurant_recommend_node(state)
    item = patch["recommended_pois"]["restaurant"][0]

    assert item["category"] == POI_RESTAURANT
    assert item["estimated_duration_minutes"] == 90
    assert isinstance(item["reservation_required"], bool)
    assert item["crowd_risk"] in {"low", "medium", "high"}
    assert item["budget_fit"] in {"good", "tight", "over_budget", "unknown"}
    assert item["scene_fit"] >= 0.9


def test_lifestyle_skill_marks_reservation_and_weak_fitness_preference() -> None:
    """生活方式 Skill 应区分娱乐/美容/健身，并标出弱偏好健身风险。"""

    state = create_initial_state("周末和朋友吃饭看电影", user_profile={"use_database": False})
    state["constraints"] = {
        "duration_hours": 4,
        "budget": 600,
        "people_count": 2,
        "scenario": "friends",
    }
    state["candidate_pois"] = poi_collector_node({
        **state,
        "dag_plan": {"collector_categories": [POI_ENTERTAINMENT, POI_BEAUTY, POI_FITNESS]},
    })["candidate_pois"]

    patch = poi_lifestyle_recommend_node(state)
    items = patch["recommended_pois"]["lifestyle"]

    assert items
    assert all("estimated_duration_minutes" in item for item in items)
    assert all(item["reservation_required"] is True for item in items)
    assert all(item["budget_fit"] in {"good", "tight", "over_budget", "unknown"} for item in items)
    fitness = next(item for item in items if item["category"] == POI_FITNESS)
    assert "weak_preference_match" in fitness["risk_flags"]

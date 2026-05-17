from __future__ import annotations

from app.agents.poi_collector import poi_collector_node
from app.state.plan_state import create_initial_state
from app.tools.poi_activity_recommend import poi_activity_recommend_node
from app.tools.poi_schema import POI_ACTIVITY, POI_RESTAURANT


def test_collector_outputs_unified_poi_fields() -> None:
    """Collector 输出必须稳定满足统一 POI 字段，避免后续 Skill 依赖高德原始字段。"""

    state = create_initial_state("周末出去玩", user_profile={"use_database": False})
    state["dag_plan"] = {"collector_categories": [POI_ACTIVITY, POI_RESTAURANT]}

    patch = poi_collector_node(state)
    activity = patch["candidate_pois"][POI_ACTIVITY][0]

    assert set(activity) == {
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
    assert activity["category"] == POI_ACTIVITY


def test_activity_skill_outputs_scored_recommendations() -> None:
    """Skill 层只消费统一 POI，并输出带 score/reason/risk_flags 的推荐候选。"""

    state = create_initial_state("周末体验活动", user_profile={"use_database": False})
    state["candidate_pois"] = poi_collector_node(
        {
            **state,
            "dag_plan": {"collector_categories": [POI_ACTIVITY]},
        }
    )["candidate_pois"]

    patch = poi_activity_recommend_node(state)
    item = patch["recommended_pois"]["activity"][0]

    assert item["category"] == POI_ACTIVITY
    assert item["score"] > item["rating"]
    assert item["reason"]
    assert item["risk_flags"] == []

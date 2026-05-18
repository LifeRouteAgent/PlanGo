from __future__ import annotations

from app.agents.issue_utils import make_issue
from app.agents.ranker import ranker_node
from app.state.plan_state import create_initial_state


def test_ranker_prefers_overall_plan_score_over_item_count() -> None:
    """整体方案排序应优先可执行质量，而不是简单选 POI 更多的方案。"""

    state = create_initial_state("周末和朋友出去玩 4 小时，想吃饭看电影")
    state["intent_type"] = "full_trip_plan"
    state["constraints"] = {"duration_hours": 4, "max_route_minutes": 45, "budget": 600}
    state["dag_plan"] = {"required_slots": ["activity_or_entertainment", "restaurant"]}
    state["verified_plans"] = [
        {
            "id": "many_but_risky",
            "items": [
                _poi("movie", "poi_entertainment", 4.8, 0.9),
                _poi("ktv", "poi_entertainment", 4.7, 0.8),
                _poi("food", "poi_restaurant", 4.6, 0.9),
            ],
            "route_minutes": 44,
            "total_duration_minutes": 240,
            "estimated_budget": 560,
            "issues": [
                make_issue("duplicate_category", source="test"),
                make_issue("queue_risk", source="test"),
                make_issue("open_time_unknown", source="test"),
            ],
            "verified": True,
        },
        {
            "id": "compact_and_clear",
            "items": [
                _poi("movie2", "poi_entertainment", 4.5, 0.9),
                _poi("food2", "poi_restaurant", 4.4, 0.9),
            ],
            "route_minutes": 12,
            "total_duration_minutes": 210,
            "estimated_budget": 300,
            "issues": [],
            "verified": True,
        },
    ]

    patch = ranker_node(state)

    assert patch["selected_plan"]["id"] == "compact_and_clear"
    assert patch["ranked_plans"][0]["plan_score"] > patch["ranked_plans"][1]["plan_score"]
    assert "score_breakdown" in patch["selected_plan"]


def test_category_ranker_uses_recommendation_score() -> None:
    """分类推荐应按综合 recommendation_score 排序，而不是只看原始 score。"""

    state = create_initial_state("推荐餐厅")
    state["intent_type"] = "category_recommend"
    state["recommended_pois"] = {
        "restaurant": [
            {
                **_poi("high_score_bad_fit", "poi_restaurant", 5.0, 0.3),
                "budget_fit": "over_budget",
                "crowd_risk": "high",
            },
            {
                **_poi("lower_score_good_fit", "poi_restaurant", 4.5, 0.95),
                "budget_fit": "good",
                "crowd_risk": "low",
            },
        ]
    }

    patch = ranker_node(state)
    items = patch["selected_plan"]["items"]

    assert items[0]["id"] == "lower_score_good_fit"
    assert items[0]["recommendation_score"] > items[1]["recommendation_score"]


def _poi(poi_id: str, category: str, rating: float, scene_fit: float) -> dict:
    """构造 Ranker 测试所需的推荐 POI。"""

    return {
        "id": poi_id,
        "name": poi_id,
        "category": category,
        "subcategory": category,
        "lat": 39.9,
        "lon": 116.4,
        "address": "测试地址",
        "rating": rating,
        "price_level": "medium",
        "open_status": "open",
        "tags": [],
        "score": rating,
        "reason": "测试",
        "risk_flags": [],
        "estimated_duration_minutes": 90,
        "reservation_required": False,
        "crowd_risk": "low",
        "budget_fit": "good",
        "scene_fit": scene_fit,
        "distance_sensitive": True,
    }

from __future__ import annotations

from app.agents.route_planner import _build_route_segments, route_time_planner_node
from app.services.amap_route_service import AmapRouteEstimate
from app.state.plan_state import create_initial_state


def test_route_planner_prefers_nearby_restaurant_over_far_high_score() -> None:
    """路线规划应优先选择动线可执行的近餐厅，而不是盲目选择远处高分餐厅。"""

    state = create_initial_state("周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600")
    state["constraints"] = {
        "start_time": "14:00",
        "duration_hours": 4,
        "max_route_minutes": 45,
    }
    state["dag_plan"] = {
        "planning_template": "friends_gathering",
        "required_slots": ["activity_or_entertainment", "restaurant"],
        "movement_policy": "compact_walk_or_taxi",
        "candidate_strategy": "slot_balance",
    }
    state["recommended_pois"] = {
        "lifestyle": [
            _poi("movie", "附近影院", "poi_entertainment", 39.9, 116.4, 4.8, 120),
        ],
        "restaurant": [
            _poi("far_food", "远处高分餐厅", "poi_restaurant", 40.8, 117.3, 5.0, 90),
            _poi("near_food", "附近餐厅", "poi_restaurant", 39.905, 116.405, 4.2, 90),
        ],
    }

    patch = route_time_planner_node(state)
    plan = patch["candidate_plans"][0]

    assert [item["id"] for item in plan["items"]] == ["movie", "near_food"]
    assert plan["route_minutes"] <= 45
    assert plan["total_duration_minutes"] <= 240
    assert plan["route_segments"][0]["transport_mode"] == "walk"
    assert plan["timeline"][1]["travel_from_previous_minutes"] > 0
    assert plan["timeline"][1]["distance_from_previous_km"] < 1


def test_route_planner_generates_plan_slot_timeline_fields() -> None:
    """时间线应包含 PlanSlot 所需的开始/结束时间、停留、交通方式和距离。"""

    state = create_initial_state("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")
    state["constraints"] = {
        "start_time": "14:00",
        "duration_hours": 4,
        "max_route_minutes": 45,
    }
    state["dag_plan"] = {
        "planning_template": "friends_gathering",
        "required_slots": ["activity_or_entertainment", "restaurant"],
        "movement_policy": "compact_walk_or_taxi",
        "candidate_strategy": "slot_balance",
    }
    state["recommended_pois"] = {
        "lifestyle": [
            _poi("movie", "影院", "poi_entertainment", 39.9, 116.4, 4.8, 120),
        ],
        "restaurant": [
            _poi("food", "餐厅", "poi_restaurant", 39.95, 116.45, 4.6, 90),
        ],
    }

    patch = route_time_planner_node(state)
    slot = patch["candidate_plans"][0]["timeline"][0]
    second_slot = patch["candidate_plans"][0]["timeline"][1]

    assert slot.keys() >= {
        "slot_type",
        "poi_id",
        "start_time",
        "end_time",
        "stay_minutes",
        "travel_from_previous_minutes",
        "transport_mode",
        "distance_from_previous_km",
    }
    assert slot["transport_mode"] == "start"
    assert second_slot["transport_mode"] in {"taxi", "transit_or_taxi"}


def test_route_planner_falls_back_to_haversine_without_amap_key() -> None:
    """没有高德 key 或 service 时，路线段应保留 Haversine 兜底来源。"""

    segments = _build_route_segments(
        [
            _poi("movie", "影院", "poi_entertainment", 39.9, 116.4, 4.8, 120),
            _poi("food", "餐厅", "poi_restaurant", 39.905, 116.405, 4.6, 90),
        ],
        route_service=None,
    )

    assert segments[0]["source"] == "haversine_estimated"
    assert segments[0]["distance_km"] > 0
    assert segments[0]["duration_minutes"] > 0


def test_route_planner_uses_amap_estimate_when_available() -> None:
    """高德路线结果可用时，应覆盖 Haversine 的距离和耗时。"""

    segments = _build_route_segments(
        [
            _poi("movie", "影院", "poi_entertainment", 39.9, 116.4, 4.8, 120),
            _poi("food", "餐厅", "poi_restaurant", 39.905, 116.405, 4.6, 90),
        ],
        route_service=_FakeAmapRouteService(),
    )

    assert segments[0]["source"] == "amap_driving"
    assert segments[0]["distance_km"] == 2.5
    assert segments[0]["duration_minutes"] == 18
    assert segments[0]["fallback_distance_km"] > 0


def _poi(
    poi_id: str,
    name: str,
    category: str,
    lat: float,
    lon: float,
    rating: float,
    duration: int,
) -> dict:
    """构造 Route Planner 测试所需的推荐 POI。"""

    return {
        "id": poi_id,
        "name": name,
        "category": category,
        "subcategory": category,
        "lat": lat,
        "lon": lon,
        "address": "测试地址",
        "rating": rating,
        "price_level": "medium",
        "open_status": "open",
        "tags": [],
        "score": rating,
        "reason": "测试候选",
        "risk_flags": [],
        "estimated_duration_minutes": duration,
        "reservation_required": True,
        "crowd_risk": "medium",
        "budget_fit": "good",
        "scene_fit": 0.9,
        "distance_sensitive": True,
    }


class _FakeAmapRouteService:
    """测试替身：模拟高德返回真实路线耗时。"""

    def estimate_segment(self, *args, **kwargs) -> AmapRouteEstimate:
        return AmapRouteEstimate(distance_km=2.5, duration_minutes=18, source="amap_driving")

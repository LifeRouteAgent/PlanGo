from __future__ import annotations

from app.agents.route_planner import _build_route_segments, route_time_planner_node
from app.services.amap_route_service import AmapRouteEstimate, AmapRouteService
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


def test_route_planner_uses_slot_combination_search_and_returns_three_plans() -> None:
    """Route Planner 应按 slot 组合搜索生成最多 3 个结构完整的候选方案。"""

    state = create_initial_state("朋友周末想先打麻将再唱歌，4 小时，预算 300")
    state["constraints"] = {
        "start_time": "10:00",
        "duration_hours": 4,
        "max_route_minutes": 60,
        "budget": 300,
        "activity_intents": [
            {"must_match": True, "semantic_type": "ktv", "keywords": ["KTV", "唱歌"]},
            {"must_match": True, "semantic_type": "chess_cards", "keywords": ["麻将", "桌游"]},
        ],
    }
    state["dag_plan"] = {
        "planning_template": "entertainment_gathering",
        "required_slots": ["entertainment", "optional_entertainment"],
        "slot_sequence": ["entertainment", "optional_entertainment"],
        "movement_policy": "compact_walk_or_taxi",
        "candidate_strategy": "slot_combination",
    }
    state["recommended_pois"] = {
        "lifestyle": [
            _poi("mahjong_1", "麻将馆 A", "poi_entertainment", 39.9, 116.4, 4.8, 90),
            _poi("ktv_1", "KTV A", "poi_entertainment", 39.902, 116.402, 4.7, 90),
            _poi("ktv_2", "KTV B", "poi_entertainment", 39.91, 116.41, 4.6, 90),
            _poi("board_1", "桌游店 A", "poi_entertainment", 39.93, 116.43, 4.5, 90),
            _poi("mahjong_2", "麻将馆 B", "poi_entertainment", 39.94, 116.44, 4.4, 90),
            _poi("ktv_3", "KTV C", "poi_entertainment", 39.945, 116.445, 4.3, 90),
        ],
    }

    patch = route_time_planner_node(state)
    plans = patch["candidate_plans"]

    assert len(plans) == 3
    used_ids: set[str] = set()
    for plan in plans:
        assert plan.keys() >= {
            "plan_id",
            "items",
            "timeline",
            "route_segments",
            "estimated_budget",
            "total_duration_minutes",
            "route_minutes",
            "fit_summary",
        }
        assert len(plan["items"]) <= 2
        assert plan["fit_summary"]["slot_count"] == len(plan["items"])
        item_ids = {item["id"] for item in plan["items"]}
        assert item_ids.isdisjoint(used_ids)
        used_ids.update(item_ids)
        if plan["route_segments"]:
            assert plan["route_segments"][0].keys() >= {"from_item_id", "to_item_id", "source"}


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


def test_amap_service_uses_tool_harness_fallback_without_key() -> None:
    """高德 key 缺失时，服务应通过 ToolHarness 返回 fallback_haversine。"""

    service = AmapRouteService(api_key="")
    estimate = service.estimate_segment(
        _poi("movie", "影院", "poi_entertainment", 39.9, 116.4, 4.8, 120),
        _poi("food", "餐厅", "poi_restaurant", 39.905, 116.405, 4.6, 90),
        fallback_distance_km=0.7,
    )

    assert estimate is not None
    assert estimate.source == "fallback_haversine"
    assert estimate.distance_km == 0.7
    assert service.call_log
    assert service.call_log[-1]["tool"] == "amap.route.estimate_segment"


def test_route_planner_adds_origin_segment_when_profile_has_start_location() -> None:
    """用户画像提供起点坐标时，第一站应展示从起点出发的距离和耗时。"""

    state = create_initial_state(
        "下午从家出发看电影吃饭",
        user_profile={"start_location": {"name": "家", "lat": 39.895, "lon": 116.395}},
    )
    state["constraints"] = {
        "start_time": "14:00",
        "duration_hours": 4,
        "max_route_minutes": 60,
    }
    state["dag_plan"] = {
        "planning_template": "friends_gathering",
        "required_slots": ["entertainment", "restaurant"],
        "movement_policy": "compact_walk_or_taxi",
        "candidate_strategy": "slot_balance",
    }
    state["recommended_pois"] = {
        "lifestyle": [
            _poi("movie", "影院", "poi_entertainment", 39.9, 116.4, 4.8, 90),
        ],
        "restaurant": [
            _poi("food", "餐厅", "poi_restaurant", 39.905, 116.405, 4.6, 80),
        ],
    }

    patch = route_time_planner_node(state)
    plan = patch["candidate_plans"][0]

    assert len(plan["route_segments"]) == len(plan["items"])
    assert plan["route_segments"][0]["from_item_id"] == "origin"
    assert plan["timeline"][0]["travel_from_previous_minutes"] > 0
    assert plan["timeline"][0]["distance_from_previous_km"] > 0
    assert plan["timeline"][0]["transport_mode"] != "start"


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

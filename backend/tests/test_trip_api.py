from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import app
from app.api.routes.trip import _build_agent_thinking_payload, _trace_events_for_node


def test_trip_plan_api_runs_langgraph_dag() -> None:
    """HTTP API 应能触发完整 LangGraph DAG，并返回模拟执行后的方案。"""

    client = TestClient(app)
    response = client.post(
        "/trip/plan",
        json={"user_query": "周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["execution_status"] == "simulated"
    assert str(body["selected_plan"]["id"]).startswith("v2_plan_")
    assert body["selected_plan"]["plan_score"] > 0
    assert body["response_payload"]["response_type"] == "plan_cards"
    assert body["response_payload"]["plans"]
    assert body["response_text"]


def test_agent_thinking_payload_hides_internal_english_logs() -> None:
    """?????? V2 ??????????????????????"""

    events = [
        _build_agent_thinking_payload(
            "availability_checker",
            {"logs": ["Availability Checker: all mock POIs are available"]},
            {},
        ),
        _build_agent_thinking_payload(
            "candidate_pool_balancer",
            {"balanced_candidates": {"activity_or_entertainment": [{"id": "poi_1"}]}},
            {},
        ),
        _build_agent_thinking_payload(
            "final_ranker",
            {"ranked_plans": [{"id": "plan_1"}]},
            {},
        ),
    ]

    assert all(event["title"] for event in events)
    assert all("Checker" not in event["message"] for event in events)
    assert all("{" not in event["message"] for event in events)
    assert all("restaurant" not in event["message"] for event in events)
    assert all("lifestyle" not in event["message"] for event in events)

def test_trace_events_expose_product_progress_without_raw_state() -> None:
    """SSE ???????? V2 ??????????? PlanState ??? POI ???"""

    intent_events = _trace_events_for_node(
        "intent_resolver",
        {"intent_type": "full_trip_plan", "answer_mode": "full_trip_plan"},
        {
            "intent_type": "full_trip_plan",
            "answer_mode": "full_trip_plan",
            "target_categories": ["entertainment"],
        },
    )
    planner_events = _trace_events_for_node(
        "planner",
        {},
        {
            "planning_strategy": {
                "planning_template": "friends_gathering",
                "collector_categories": ["poi_entertainment"],
                "slot_sequence": ["entertainment", "entertainment"],
            }
        },
    )
    route_events = _trace_events_for_node(
        "route_planner",
        {},
        {
            "candidate_plans": [{
                "id": "plan_1",
                "total_duration_minutes": 240,
                "route_minutes": 18,
                "estimated_budget": 180,
            }]
        },
    )
    ranker_events = _trace_events_for_node(
        "final_ranker",
        {},
        {"ranked_plans": [{"id": "plan_1", "plan_score": 88}]},
    )

    assert intent_events[0][0] == "intent_detected"
    assert planner_events[0][0] == "planning_strategy_selected"
    assert route_events[0][0] == "route_candidate_built"
    assert ranker_events[0][0] == "plan_ranked"
    assert route_events[0][1]["candidate_plan_count"] == 1

def test_adjust_plan_recalculates_route_budget_and_issues() -> None:
    """局部替换某一站后，应重新计算路线、时间线、预算和 Verifier 结果。"""

    client = TestClient(app)
    plan = {
        "id": "plan_adjust_test",
        "title": "测试方案",
        "items": [
            _adjust_poi("old_food", "旧餐厅", "poi_restaurant", 39.9, 116.4),
            _adjust_poi("movie", "影院", "poi_entertainment", 39.91, 116.41),
        ],
        "timeline": [
            {
                "order": 1,
                "slot_type": "restaurant",
                "poi_id": "old_food",
                "title": "旧餐厅",
                "start_time": "14:00",
                "end_time": "15:00",
                "stay_minutes": 60,
            },
            {
                "order": 2,
                "slot_type": "entertainment",
                "poi_id": "movie",
                "title": "影院",
                "start_time": "15:15",
                "end_time": "16:45",
                "stay_minutes": 90,
            },
        ],
        "route_segments": [],
        "route_minutes": 0,
        "total_duration_minutes": 150,
        "estimated_budget": 200,
    }

    response = client.post(
        "/trip/plan/adjust",
        json={"plan": plan, "poi_id": "old_food", "prompt": "换个更近一点的餐厅"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["plan"]["id"] == "plan_adjust_test"
    assert body["plan"]["items"][0]["id"] != "old_food"
    assert "timeline" in body["plan"]
    assert "route_minutes" in body["plan"]
    assert "estimated_budget" in body["plan"]
    assert "recommendation_reason" in body["plan"]
    assert "issues" in body


def _adjust_poi(
    poi_id: str,
    name: str,
    category: str,
    lat: float,
    lon: float,
) -> dict:
    """构造局部调整测试用 POI。"""

    return {
        "id": poi_id,
        "name": name,
        "category": category,
        "subcategory": category,
        "lat": lat,
        "lon": lon,
        "address": "测试地址",
        "rating": 4.6,
        "price_level": "medium",
        "open_status": "open",
        "tags": [],
        "score": 4.8,
        "reason": "测试",
        "risk_flags": [],
        "estimated_duration_minutes": 60 if category == "poi_restaurant" else 90,
        "reservation_required": True,
        "crowd_risk": "medium",
        "budget_fit": "good",
        "scene_fit": 0.9,
        "distance_sensitive": True,
    }

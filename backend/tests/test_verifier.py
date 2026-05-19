from __future__ import annotations

from app.agents.issue_utils import has_blocking_issue, issue_codes
from app.agents.verifier import verifier_node, verifier_route
from app.state.plan_state import create_initial_state


def test_verifier_outputs_structured_blocking_issue() -> None:
    """路线超时应输出结构化 error，并阻断进入 Ranker。"""

    state = create_initial_state("周末和朋友吃饭看电影 4 小时")
    state["constraints"] = {"duration_hours": 4, "max_route_minutes": 45, "budget": 600}
    state["candidate_plans"] = [{
        "id": "bad_route",
        "items": [_poi("movie", "poi_entertainment"), _poi("food", "poi_restaurant")],
        "route_minutes": 80,
        "total_duration_minutes": 230,
        "estimated_budget": 300,
        "route_segments": [{
            "from": "影院",
            "to": "餐厅",
            "distance_km": 20,
            "transport_mode": "cross_district_taxi",
            "duration_minutes": 80,
        }],
    }]

    patch = verifier_node(state)
    issue = patch["errors"][0]

    assert issue["code"] == "route_timeout"
    assert issue["severity"] == "error"
    assert issue["message"]
    assert issue["suggestion"]
    assert has_blocking_issue(patch["errors"]) is True


def test_verifier_warning_does_not_block_verified_plan() -> None:
    """预约和排队风险是 warning，应保留方案并允许进入 Ranker。"""

    state = create_initial_state("周末和朋友吃饭看电影 4 小时")
    state["constraints"] = {"duration_hours": 4, "max_route_minutes": 45, "budget": 600}
    state["candidate_plans"] = [{
        "id": "warning_plan",
        "items": [
            {
                **_poi("movie", "poi_entertainment"),
                "reservation_required": True,
                "crowd_risk": "high",
                "risk_flags": ["queue_risk"],
            },
            _poi("food", "poi_restaurant"),
        ],
        "route_minutes": 20,
        "total_duration_minutes": 220,
        "estimated_budget": 300,
        "route_segments": [{
            "from": "影院",
            "to": "餐厅",
            "distance_km": 3,
            "transport_mode": "taxi",
            "duration_minutes": 20,
        }],
    }]

    patch = verifier_node(state)
    merged = {**state, **patch}

    assert patch["verified_plans"][0]["verified"] is True
    assert issue_codes(patch["errors"]) >= {"queue_risk", "reservation_required"}
    assert has_blocking_issue(patch["errors"]) is False
    assert verifier_route(merged) == "rank"


def _poi(poi_id: str, category: str) -> dict:
    """构造 Verifier 测试所需的推荐 POI。"""

    return {
        "id": poi_id,
        "name": poi_id,
        "category": category,
        "subcategory": category,
        "lat": 39.9,
        "lon": 116.4,
        "address": "测试地址",
        "rating": 4.5,
        "price_level": "medium",
        "open_status": "open",
        "tags": [],
        "score": 4.8,
        "reason": "测试",
        "risk_flags": [],
        "estimated_duration_minutes": 90,
        "reservation_required": False,
        "crowd_risk": "low",
        "budget_fit": "good",
        "scene_fit": 0.9,
        "distance_sensitive": True,
    }

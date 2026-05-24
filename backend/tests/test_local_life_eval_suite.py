from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agents.constraint_builder import constraint_builder_node
from app.agents.constraint_clarifier import constraint_clarifier_node
from app.agents.intent_router import intent_router_node, intent_router_route
from app.agents.planner_agent import planner_agent_node
from app.agents.ranker import ranker_node
from app.agents.route_planner import route_time_planner_node
from app.agents.verifier import _issues_for_plan, verifier_node
from app.state.plan_state import PlanState, PlanStatePatch, create_initial_state
from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
)


@dataclass(frozen=True)
class EvalCase:
    """本地生活 Agent 的轻量评测样本。

    这些样本固定“理解 -> 追问 -> Planner 选 Skill”关键链路，避免后续改 prompt、
    规则或模板时把核心意图能力改坏。
    """

    query: str
    intent_type: str
    target_categories: list[str] = field(default_factory=list)
    need_clarification: bool = False
    missing_constraints: list[str] = field(default_factory=list)
    scenario: str = "unknown"
    people_count: int | None = None
    preferences: list[str] = field(default_factory=list)
    start_time: str | None = None
    duration_hours: int | None = None
    budget: int | None = None
    planning_template: str = ""
    required_slots: list[str] = field(default_factory=list)
    expected_enabled_skills: set[str] = field(default_factory=set)


EVAL_CASES: list[EvalCase] = [
    EvalCase("你好", "simple_qa"),
    EvalCase("谢谢", "simple_qa"),
    EvalCase("你是什么模型", "simple_qa"),
    EvalCase("你用的什么模型", "simple_qa"),
    EvalCase("你能做什么", "capability"),
    EvalCase("这个系统怎么用", "capability"),
    EvalCase(
        "推荐几个适合朋友聚会的餐厅",
        "category_recommend",
        [POI_RESTAURANT],
        preferences=["聚餐"],
        expected_enabled_skills={"poi_restaurant_recommend"},
    ),
    EvalCase(
        "附近有没有 KTV 推荐",
        "category_recommend",
        [POI_ENTERTAINMENT],
        preferences=["KTV"],
        expected_enabled_skills={"poi_lifestyle_recommend"},
    ),
    EvalCase(
        "找个按摩足疗店",
        "poi_search",
        [POI_BEAUTY],
        preferences=["按摩"],
        expected_enabled_skills={"poi_lifestyle_recommend"},
    ),
    EvalCase(
        "推荐周末活动",
        "category_recommend",
        [POI_ACTIVITY],
        preferences=["活动"],
        expected_enabled_skills={"poi_activity_recommend"},
    ),
    EvalCase(
        "只想找附近商场逛街",
        "poi_search",
        [POI_SHOPPING],
        preferences=["逛街"],
        expected_enabled_skills={"poi_mix_recommend"},
    ),
    EvalCase(
        "今晚 2 个人吃火锅，预算 300",
        "poi_search",
        [POI_RESTAURANT],
        people_count=2,
        preferences=["火锅"],
        budget=300,
        expected_enabled_skills={"poi_restaurant_recommend"},
    ),
    EvalCase(
        "推荐几个适合亲子的室内活动",
        "category_recommend",
        [POI_ACTIVITY],
        scenario="family",
        preferences=["亲子", "室内活动"],
        expected_enabled_skills={"poi_activity_recommend"},
    ),
    EvalCase(
        "推荐一个美容 SPA",
        "category_recommend",
        [POI_BEAUTY],
        preferences=["美容", "SPA"],
        expected_enabled_skills={"poi_lifestyle_recommend"},
    ),
    EvalCase(
        "周末想出去玩",
        "full_trip_plan",
        need_clarification=True,
        missing_constraints=["people_or_scenario", "time_window", "preference"],
        planning_template="meal_plus_activity",
    ),
    EvalCase(
        "周六下午带孩子玩半天，想室内活动加吃饭，预算 500",
        "full_trip_plan",
        [POI_ACTIVITY, POI_RESTAURANT],
        scenario="family",
        people_count=3,
        preferences=["亲子", "室内活动", "吃饭"],
        start_time="14:00",
        duration_hours=4,
        budget=500,
        planning_template="family_half_day",
        required_slots=["family_activity", "restaurant", "optional_shopping"],
        expected_enabled_skills={
            "poi_activity_recommend",
            "poi_restaurant_recommend",
            "poi_mix_recommend",
        },
    ),
    EvalCase(
        "周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600，别太远",
        "full_trip_plan",
        [POI_RESTAURANT, POI_ENTERTAINMENT],
        scenario="friends",
        people_count=4,
        preferences=["吃饭", "电影"],
        start_time="14:00",
        duration_hours=4,
        budget=600,
        planning_template="friends_gathering",
        required_slots=["activity_or_entertainment", "restaurant", "optional_lifestyle"],
        expected_enabled_skills={
            "poi_lifestyle_recommend",
            "poi_restaurant_recommend",
            "poi_activity_recommend",
        },
    ),
    EvalCase(
        "周末上午和朋友出去玩 4 个小时，想去打麻将打牌然后去唱歌，预算 200",
        "full_trip_plan",
        [POI_ENTERTAINMENT],
        scenario="friends",
        people_count=4,
        preferences=["麻将", "唱歌"],
        start_time="10:00",
        duration_hours=4,
        budget=200,
        planning_template="entertainment_gathering",
        required_slots=["entertainment", "optional_entertainment"],
        expected_enabled_skills={"poi_lifestyle_recommend"},
    ),
    EvalCase(
        "情侣晚上看展吃饭散步 5 小时预算 800",
        "full_trip_plan",
        [POI_ACTIVITY, POI_RESTAURANT, POI_ATTRACTION],
        scenario="couple",
        people_count=2,
        preferences=["看展", "吃饭", "散步"],
        start_time="18:00",
        duration_hours=5,
        budget=800,
        planning_template="couple_date",
        required_slots=["activity", "restaurant", "cafe_or_walk"],
        expected_enabled_skills={
            "poi_activity_recommend",
            "poi_restaurant_recommend",
            "poi_mix_recommend",
        },
    ),
    EvalCase(
        "闺蜜周日下午按摩再喝咖啡 3 小时预算 400",
        "full_trip_plan",
        [POI_BEAUTY, POI_RESTAURANT],
        scenario="friends",
        people_count=2,
        preferences=["按摩", "咖啡"],
        start_time="14:00",
        duration_hours=3,
        budget=400,
        planning_template="relaxation",
        required_slots=["lifestyle", "restaurant_or_tea", "optional_shopping"],
        expected_enabled_skills={
            "poi_lifestyle_recommend",
            "poi_restaurant_recommend",
            "poi_mix_recommend",
        },
    ),
    EvalCase(
        "周末下午想运动一下再吃饭 4 小时预算 300",
        "full_trip_plan",
        [POI_FITNESS, POI_RESTAURANT],
        scenario="friends",
        people_count=2,
        preferences=["运动", "吃饭"],
        start_time="14:00",
        duration_hours=4,
        budget=300,
        planning_template="meal_plus_activity",
        required_slots=["activity", "restaurant"],
        expected_enabled_skills={
            "poi_lifestyle_recommend",
            "poi_activity_recommend",
            "poi_restaurant_recommend",
        },
    ),
    EvalCase(
        "明天下午 3 小时朋友桌游，然后晚饭预算 500",
        "full_trip_plan",
        [POI_ENTERTAINMENT, POI_RESTAURANT],
        scenario="friends",
        people_count=4,
        preferences=["桌游", "晚饭"],
        start_time="14:00",
        duration_hours=3,
        budget=500,
        planning_template="friends_gathering",
        required_slots=["activity_or_entertainment", "restaurant"],
        expected_enabled_skills={
            "poi_lifestyle_recommend",
            "poi_restaurant_recommend",
            "poi_activity_recommend",
        },
    ),
    EvalCase(
        "周六上午老人一起公园散步吃饭 4 小时预算 300",
        "full_trip_plan",
        [POI_ATTRACTION, POI_RESTAURANT],
        scenario="family",
        people_count=3,
        preferences=["公园", "散步", "吃饭"],
        start_time="10:00",
        duration_hours=4,
        budget=300,
        planning_template="family_half_day",
        required_slots=["family_activity", "restaurant"],
        expected_enabled_skills={
            "poi_mix_recommend",
            "poi_activity_recommend",
            "poi_restaurant_recommend",
        },
    ),
    EvalCase(
        "今天太热，不要室外，下午 4 小时朋友聚会",
        "full_trip_plan",
        [POI_ENTERTAINMENT, POI_SHOPPING],
        scenario="friends",
        people_count=4,
        preferences=["室内", "朋友聚会"],
        start_time="14:00",
        duration_hours=4,
        planning_template="friends_gathering",
        required_slots=["activity_or_entertainment", "restaurant"],
        expected_enabled_skills={
            "poi_lifestyle_recommend",
            "poi_restaurant_recommend",
            "poi_activity_recommend",
        },
    ),
    EvalCase(
        "预算只有 100，想和朋友简单吃点再逛逛",
        "full_trip_plan",
        [POI_RESTAURANT, POI_SHOPPING],
        scenario="friends",
        people_count=2,
        preferences=["便宜", "吃饭", "逛街"],
        duration_hours=3,
        budget=100,
        planning_template="shopping_leisure",
        required_slots=["shopping", "restaurant"],
        expected_enabled_skills={"poi_restaurant_recommend", "poi_mix_recommend"},
    ),
    EvalCase(
        "给我安排一个周日亲子半日，不要太远",
        "full_trip_plan",
        [POI_ACTIVITY, POI_RESTAURANT],
        scenario="family",
        people_count=3,
        preferences=["亲子", "近一点"],
        duration_hours=4,
        planning_template="family_half_day",
        required_slots=["family_activity", "restaurant"],
        expected_enabled_skills={"poi_activity_recommend", "poi_restaurant_recommend"},
    ),
    EvalCase(
        "晚上想约会，不想太吵，吃饭加轻松活动",
        "full_trip_plan",
        [POI_RESTAURANT, POI_ACTIVITY],
        scenario="couple",
        people_count=2,
        preferences=["约会", "安静", "吃饭"],
        start_time="18:00",
        duration_hours=4,
        planning_template="couple_date",
        required_slots=["activity", "restaurant"],
        expected_enabled_skills={"poi_activity_recommend", "poi_restaurant_recommend"},
    ),
    EvalCase(
        "朋友生日，晚饭后 KTV，预算 1000",
        "full_trip_plan",
        [POI_RESTAURANT, POI_ENTERTAINMENT],
        scenario="friends",
        people_count=6,
        preferences=["生日", "晚饭", "KTV"],
        start_time="18:00",
        duration_hours=5,
        budget=1000,
        planning_template="friends_gathering",
        required_slots=["restaurant", "entertainment"],
        expected_enabled_skills={"poi_restaurant_recommend", "poi_lifestyle_recommend"},
    ),
    EvalCase(
        "一个人周末想找咖啡馆看看书",
        "category_recommend",
        [POI_RESTAURANT],
        scenario="solo",
        people_count=1,
        preferences=["咖啡", "安静"],
        expected_enabled_skills={"poi_restaurant_recommend"},
    ),
    EvalCase(
        "查一下附近羽毛球馆",
        "poi_search",
        [POI_FITNESS],
        preferences=["羽毛球"],
        expected_enabled_skills={"poi_lifestyle_recommend"},
    ),
    EvalCase(
        "周末晚上想去密室再夜宵",
        "full_trip_plan",
        [POI_ENTERTAINMENT, POI_RESTAURANT],
        scenario="friends",
        people_count=4,
        preferences=["密室", "夜宵"],
        start_time="19:00",
        duration_hours=4,
        planning_template="entertainment_gathering",
        required_slots=["entertainment", "restaurant"],
        expected_enabled_skills={"poi_lifestyle_recommend", "poi_restaurant_recommend"},
    ),
]


@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda case: case.query)
def test_eval_intent_clarifier_and_skill_selection(
    monkeypatch: pytest.MonkeyPatch, case: EvalCase
) -> None:
    """典型本地生活输入应稳定产出正确意图、追问状态和 Skill 选择。"""

    monkeypatch.setattr(
        "app.agents.intent_router.build_llm_understanding",
        lambda query, user_profile: _llm_payload(case),
    )

    state = _run_understanding_pipeline(case.query)

    assert state["intent_type"] == case.intent_type
    assert state["target_categories"] == case.target_categories
    if case.intent_type in {"capability", "simple_qa"}:
        assert intent_router_route(state) == "direct_answer"
        assert state["dag_plan"] == {}
        return

    assert state["need_clarification"] is case.need_clarification
    assert state["missing_constraints"] == case.missing_constraints
    if case.need_clarification:
        assert state["answer_mode"] == "clarification"
        assert state["dag_plan"] == {}
        return

    assert state["dag_plan"]["enabled_skills"]
    assert set(state["dag_plan"]["enabled_skills"]) >= case.expected_enabled_skills
    if case.planning_template:
        assert state["dag_plan"]["planning_template"] == case.planning_template
    if case.required_slots:
        assert state["dag_plan"]["slot_sequence"] == case.required_slots


def test_eval_full_plan_returns_three_ranked_plans_without_database() -> None:
    """构造推荐候选后，Route/Verifier/Ranker 应能生成 3 个可排序方案。"""

    state = create_initial_state("朋友下午打麻将唱歌 4 小时预算 300")
    state["constraints"] = {
        "start_time": "14:00",
        "duration_hours": 4,
        "budget": 300,
        "max_route_minutes": 60,
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
            _poi("mahjong_1", "麻将馆 A", POI_ENTERTAINMENT, 39.9, 116.4, 4.8, 90),
            _poi("mahjong_2", "棋牌室 B", POI_ENTERTAINMENT, 39.901, 116.401, 4.6, 80),
            _poi("ktv_1", "KTV A", POI_ENTERTAINMENT, 39.902, 116.402, 4.7, 90),
            _poi("ktv_2", "KTV B", POI_ENTERTAINMENT, 39.91, 116.41, 4.5, 90),
        ]
    }

    state = _merge_patch(state, route_time_planner_node(state))
    state = _merge_patch(state, verifier_node(state))
    state = _merge_patch(state, ranker_node(state))

    assert len(state["candidate_plans"]) == 3
    assert len(state["ranked_plans"]) == 3
    assert state["selected_plan"]["id"] == state["ranked_plans"][0]["id"]
    assert all(plan["plan_score"] > 0 for plan in state["ranked_plans"])


def test_eval_verifier_flags_route_budget_and_duration_failures() -> None:
    """预算不足、路线过长、总时长超出都应进入结构化 Verifier issue。"""

    state = create_initial_state("预算很低但想跨区玩一天")
    state["constraints"] = {"duration_hours": 2, "budget": 100, "max_route_minutes": 30}
    state["candidate_plans"] = [{
        "id": "bad_eval_plan",
        "items": [
            _poi("far_activity", "远处活动", POI_ACTIVITY, 39.9, 116.4, 4.8, 120),
            _poi("far_food", "远处餐厅", POI_RESTAURANT, 40.3, 116.8, 4.6, 90),
        ],
        "route_minutes": 80,
        "total_duration_minutes": 290,
        "estimated_budget": 260,
        "route_segments": [{
            "from": "远处活动",
            "to": "远处餐厅",
            "from_item_id": "far_activity",
            "to_item_id": "far_food",
            "distance_km": 45,
            "transport_mode": "cross_district_taxi",
            "duration_minutes": 80,
        }],
    }]

    plan = state["candidate_plans"][0]
    all_codes = {
        issue["code"]
        for issue in _issues_for_plan(plan, max_route_minutes=30, duration_limit=120, budget=100)
    }
    patch = verifier_node(state)
    blocking_codes = {issue["code"] for issue in patch["errors"]}

    assert {
        "route_timeout",
        "total_duration_exceeded",
        "budget_exceeded",
        "cross_district_move",
    } <= all_codes
    assert {"route_timeout", "total_duration_exceeded", "budget_exceeded"} <= blocking_codes
    assert all(issue["message"] and issue["suggestion"] for issue in patch["errors"])


def _run_understanding_pipeline(query: str) -> PlanState:
    """运行不依赖数据库的快速理解链路：Router -> Builder -> Clarifier -> Planner。"""

    state = create_initial_state(query)
    state = _merge_patch(state, intent_router_node(state))
    if intent_router_route(state) == "direct_answer":
        return state
    state = _merge_patch(state, constraint_builder_node(state))
    state = _merge_patch(state, constraint_clarifier_node(state))
    if not state["need_clarification"]:
        state = _merge_patch(state, planner_agent_node(state))
    return state


def _merge_patch(state: PlanState, patch: PlanStatePatch) -> PlanState:
    """在测试里模拟 LangGraph reducer 的最小合并语义。"""

    merged = dict(state)
    for key, value in patch.items():
        if key == "logs":
            merged[key] = [*merged.get(key, []), *value]
        elif key in {"candidate_pois", "recommended_pois"}:
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged  # type: ignore[return-value]


def _llm_payload(case: EvalCase) -> dict[str, Any]:
    """把 EvalCase 转成模拟 LLM 结构化理解结果。"""

    return {
        "intent_type": case.intent_type,
        "target_categories": case.target_categories,
        "scenario": case.scenario,
        "people_count": case.people_count,
        "preferences": case.preferences,
        "location_area": None,
        "start_time": case.start_time,
        "duration_hours": case.duration_hours,
        "budget": case.budget,
        "planning_template": case.planning_template,
        "required_slots": case.required_slots,
        "need_clarification": case.need_clarification,
        "missing_constraints": case.missing_constraints,
        "clarify_question": "请补充同行人、时间和偏好。" if case.need_clarification else "",
    }


def _poi(
    poi_id: str,
    name: str,
    category: str,
    lat: float,
    lon: float,
    rating: float,
    duration: int,
) -> dict[str, Any]:
    """构造 Eval 用推荐 POI，字段覆盖 Route/Verifier/Ranker 所需最小集合。"""

    return {
        "id": poi_id,
        "name": name,
        "category": category,
        "subcategory": category,
        "lat": lat,
        "lon": lon,
        "address": "测试地址",
        "rating": rating,
        "price_level": "low",
        "open_status": "open",
        "tags": [],
        "score": rating,
        "reason": "Eval 候选",
        "risk_flags": [],
        "estimated_duration_minutes": duration,
        "reservation_required": False,
        "crowd_risk": "low",
        "budget_fit": "good",
        "scene_fit": 0.9,
        "distance_sensitive": True,
        "recommendation_reason": "适合当前本地生活场景。",
        "option_prompts": ["再近一点", "换个更省钱的"],
    }

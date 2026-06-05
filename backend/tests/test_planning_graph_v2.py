from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.graph.graph_builder import run_planning_request
from app.graph.services import (
    _route_segments_for_items,
    _timeline_with_origin,
    assemble_response,
    build_constraints,
    collect_candidates,
    compile_recall_plan,
    create_route_plans,
    resolve_intent,
)
from app.graph.state import (
    CandidatePlan,
    CategoryTagRequirement,
    CompiledRecallQuery,
    IntentResult,
    LLMUnderstanding,
    OriginPoint,
    PlanningState,
    TimelineItem,
    SessionPreferenceProfile,
    ScoredPOICandidate,
    SlotRecallRequirement,
    create_planning_state,
    planning_state_to_legacy,
)
from app.services.session_preference_extractor import extract_session_preference_profile
from app.services.poi_catalog_service import PoiCatalogService
from app.models.schemas import TripPlanRequest
from app.services.trip_services import TripPlanningService


def test_minimal_planning_state_has_safe_defaults() -> None:
    state = create_planning_state("周末和朋友出去玩", session_id="s1", user_id="u1")

    assert state.state_meta.state_version == "2.0"
    assert state.state_meta.session_id == "s1"
    assert state.context.conversation_context.last_user_message == "周末和朋友出去玩"
    assert state.candidates.raw_candidates == {}
    assert state.plans.ranked_plans == []


def test_request_type_is_strict_enum() -> None:
    with pytest.raises(ValidationError):
        IntentResult(request_type="invalid")  # type: ignore[arg-type]


def test_geo_location_becomes_default_origin() -> None:
    state = create_planning_state(
        "附近找餐厅",
        geo_location={"lat": 39.9, "lng": 116.4, "source": "browser_geolocation"},
    )

    assert state.user_info.default_origin is not None
    assert state.user_info.default_origin.lat == 39.9


def test_constraint_builder_uses_defaults_without_clarification() -> None:
    understanding = resolve_intent("周末和朋友出去玩", {}, {})
    constraints, recall = build_constraints(understanding, city=None, origin=None)

    assert constraints.time_policy.duration_minutes == 270
    assert constraints.rating_policy.min_rating_initial == 4.0
    assert constraints.rating_policy.min_rating_fallback == 3.8
    assert recall.target_slots


def test_session_preference_extraction_is_available_before_constraints() -> None:
    understanding = resolve_intent("朋友聚会想唱歌KTV吃火锅，不要室外，近一点", {}, {})
    session_profile = extract_session_preference_profile(
        "朋友聚会想唱歌KTV吃火锅，不要室外，近一点",
        understanding,
    )

    constraints, _ = build_constraints(
        understanding,
        city="北京",
        origin=None,
        session_preference=session_profile,
    )

    assert "KTV" in session_profile.activity_preferences
    assert "火锅" in session_profile.dining_preferences
    assert "nearby" in session_profile.route_preferences
    assert "KTV" in constraints.soft_preferences.preference_keywords
    assert "室外" in constraints.hard_constraints.avoid_keywords


def test_session_preference_can_be_injected_without_long_term_memory() -> None:
    understanding = LLMUnderstanding(
        raw_user_message="current request",
        intent=IntentResult(request_type="full_itinerary_plan"),
    )
    session_profile = SessionPreferenceProfile(
        activity_preferences=["KTV"],
        dining_preferences=["火锅"],
        negative_preferences=["室外"],
        preferred_categories=["entertainment", "restaurant"],
    )

    constraints, _ = build_constraints(
        understanding,
        city="北京",
        origin=None,
        session_preference=session_profile,
    )

    assert "KTV" in constraints.soft_preferences.liked_logic_tags
    assert "火锅" in constraints.soft_preferences.preference_keywords
    assert "室外" in constraints.hard_constraints.avoid_keywords


def test_recall_compiler_uses_real_whitelisted_table_and_caps_limit() -> None:
    state = create_planning_state("推荐餐厅")
    understanding = LLMUnderstanding(
        raw_user_message="推荐餐厅",
        intent=IntentResult(request_type="single_category_recommend"),
    )
    constraints, recall = build_constraints(understanding, city="北京", origin=None)
    recall.slot_recall_requirements = [
        SlotRecallRequirement(slot_id="restaurant", logical_categories=["restaurant"], limit=200)
    ]

    compiled = compile_recall_plan(recall, constraints, state.context.poi_logical_tag_catalog)

    assert compiled.queries[0].physical_table == "poi_restaurant"
    assert compiled.queries[0].limit == 300
    assert "raw_extra" not in compiled.queries[0].safe_return_fields


def test_compiled_query_rejects_limit_over_500() -> None:
    with pytest.raises(ValidationError):
        CompiledRecallQuery(
            query_id="x",
            slot_id="restaurant",
            logical_category="restaurant",
            physical_table="poi_restaurant",
            limit=501,
        )


def test_compiled_query_rejects_non_whitelisted_table_and_wildcard() -> None:
    with pytest.raises(ValidationError):
        CompiledRecallQuery(
            query_id="x",
            slot_id="restaurant",
            logical_category="restaurant",
            physical_table="users",
        )
    with pytest.raises(ValidationError):
        CompiledRecallQuery(
            query_id="x",
            slot_id="restaurant",
            logical_category="restaurant",
            physical_table="poi_restaurant",
            safe_return_fields=["*"],
        )


def test_simple_qa_graph_skips_planning_nodes() -> None:
    result = run_planning_request("你好")
    nodes = [trace.node for trace in result.debug.node_trace]

    assert result.llm_understanding.intent.request_type == "simple_qa"
    assert "simple_response_generator" in nodes
    assert "route_planner" not in nodes


def test_single_category_graph_skips_route_planner() -> None:
    result = run_planning_request("推荐几个餐厅")
    nodes = [trace.node for trace in result.debug.node_trace]

    assert result.llm_understanding.intent.request_type == "single_category_recommend"
    assert "single_category_ranker" in nodes
    assert "route_planner" not in nodes


def test_plan_adjustment_uses_editor_branch(monkeypatch) -> None:
    import app.graph.services as graph_services
    from app.services.session_store import SessionStore

    monkeypatch.setattr(graph_services, "build_llm_understanding", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        SessionStore,
        "load",
        lambda self, session_id: {
            "latest_planning_state": {
                "intent_type": "full_trip_plan",
                "constraints": {"required_slots": ["activity_or_entertainment", "restaurant"]},
            },
            "latest_planning_response": {
                "response_payload": {"plans": [{"plan_id": "plan_1"}]},
                "ranked_plans": [{"id": "plan_1"}],
            },
        },
    )
    result = run_planning_request("餐厅换便宜点", session_id="adjust-session")
    nodes = [trace.node for trace in result.debug.node_trace]

    assert result.llm_understanding.intent.request_type == "plan_adjustment"
    assert "plan_editor" in nodes
    assert result.context.current_plan_state.target_edit_slots == ["restaurant"]


def test_legacy_compat_output_does_not_expose_internal_working_state() -> None:
    result = run_planning_request("你好")
    legacy = planning_state_to_legacy(result)

    assert legacy["need_clarification"] is False
    assert "recall_debug" not in legacy["debug"]
    PlanningState.model_validate(result.model_dump(mode="python"))


def test_trip_service_returns_compatible_v2_response() -> None:
    response = TripPlanningService().plan(TripPlanRequest(user_query="你好", debug=True))

    assert response.intent_type == "simple_qa"
    assert response.need_clarification is False
    assert response.response_text == response.final_text
    assert response.plan_state_id
    assert response.debug["node_trace"]


def test_frontend_plan_card_keeps_route_timeline_and_display_fields() -> None:
    payload = assemble_response(
        {
            "ranked_plans": [
                {
                    "id": "plan_1",
                    "title": "测试方案",
                    "items": [
                        {
                            "id": "poi_1",
                            "name": "测试地点",
                            "category": "poi_activity",
                            "lat": 39.9,
                            "lon": 116.4,
                            "address": "测试地址",
                            "rating": 4.8,
                            "tags": ["室内"],
                            "reason": "距离合适",
                        }
                    ],
                    "timeline": [{"poi_id": "poi_1", "start_time": "14:00", "end_time": "15:30"}],
                    "route_segments": [
                        {
                            "from": "出发地",
                            "to": "测试地点",
                            "distance_km": 2.1,
                            "duration_minutes": 12,
                            "transport_mode": "taxi",
                            "source": "amap",
                        }
                    ],
                    "total_distance_km": 2.1,
                    "route_minutes": 12,
                    "total_duration_minutes": 90,
                    "estimated_budget": 120,
                    "plan_score": 88,
                    "fit_summary": {"summary": "动线紧凑"},
                    "issues": [],
                }
            ]
        },
        "full_itinerary_plan",
    )

    plan = payload["selected_plan"]
    assert plan["id"] == "plan_1"
    assert plan["items"][0]["lat"] == 39.9
    assert plan["items"][0]["address"] == "测试地址"
    assert plan["route_segments"][0]["duration_minutes"] == 12
    assert plan["total_duration_minutes"] == 90
    assert plan["estimated_budget"] == 120
    assert plan["plan_score"] == 88


def test_database_catalog_exposes_real_filter_fields_and_tags() -> None:
    catalog = PoiCatalogService().load_catalog(query="想唱歌，不要电影院，再吃火锅")

    restaurant = catalog.tables["restaurant"]
    entertainment = catalog.tables["entertainment"]

    assert restaurant.physical_table == "poi_restaurant"
    assert "cuisine_tag" in restaurant.tag_fields
    assert "rating" in restaurant.filter_fields
    assert restaurant.total_logic_tag_count > 100
    assert "KTV" in entertainment.supported_logic_tags
    assert "电影院" in entertainment.supported_logic_tags


def test_intent_tag_mapping_only_accepts_database_catalog_tags(monkeypatch) -> None:
    import app.graph.services as graph_services

    catalog = PoiCatalogService().load_catalog(query="想唱歌")
    knowledge = PoiCatalogService().background_knowledge(catalog)
    monkeypatch.setattr(
        graph_services,
        "build_llm_understanding",
        lambda *args, **kwargs: {
            "intent_type": "category_recommend",
            "target_categories": ["poi_entertainment"],
            "required_slots": ["entertainment"],
            "category_tag_requirements": [
                {
                    "logical_category": "entertainment",
                    "target_slot": "entertainment",
                    "positive_logic_tags": ["KTV", "不存在的标签"],
                    "negative_logic_tags": ["电影院"],
                }
            ],
        },
    )

    understanding = resolve_intent("想唱歌，不要电影院", {}, {}, poi_knowledge=knowledge)
    requirement = understanding.poi_recall_intent.category_tag_requirements[0]

    assert requirement.positive_logic_tags == ["KTV"]
    assert requirement.negative_logic_tags == ["电影院"]


def test_recall_compiler_carries_category_tag_filters() -> None:
    state = create_planning_state("想唱歌")
    understanding = LLMUnderstanding(
        intent=IntentResult(request_type="single_category_recommend"),
        poi_recall_intent={
            "target_logical_categories": ["entertainment"],
            "category_tag_requirements": [
                CategoryTagRequirement(
                    logical_category="entertainment",
                    target_slot="entertainment",
                    positive_logic_tags=["KTV"],
                    negative_logic_tags=["电影院"],
                )
            ],
        },
        slots={"required_slots": ["entertainment"]},
    )
    constraints, recall = build_constraints(understanding, city="北京", origin=None)
    compiled = compile_recall_plan(recall, constraints, state.context.poi_logical_tag_catalog)

    assert compiled.queries[0].filters["positive_logic_tags"] == ["KTV"]
    assert compiled.queries[0].filters["negative_logic_tags"] == ["电影院"]


def test_catalog_rule_fallback_recognizes_tag_recommendation(monkeypatch) -> None:
    import app.graph.services as graph_services

    catalog = PoiCatalogService().load_catalog(query="推荐唱歌的地方，不要电影院")
    knowledge = PoiCatalogService().background_knowledge(catalog)
    monkeypatch.setattr(
        graph_services,
        "build_llm_understanding",
        lambda *args, **kwargs: {"intent_type": "simple_qa"},
    )

    understanding = resolve_intent(
        "推荐唱歌的地方，不要电影院",
        {},
        {},
        poi_knowledge=knowledge,
    )

    assert understanding.intent.request_type == "single_category_recommend"
    assert understanding.slots.required_slots == ["entertainment"]
    requirement = understanding.poi_recall_intent.category_tag_requirements[0]
    assert "KTV" in requirement.positive_logic_tags
    assert "电影院" in requirement.negative_logic_tags
def test_full_plan_graph_uses_v2_rank_check_loop_without_removed_nodes() -> None:
    result = run_planning_request("周末和朋友出去玩四个小时，想唱歌吃饭，预算600元")
    nodes = [trace.node for trace in result.debug.node_trace]

    assert result.llm_understanding.intent.request_type == "full_itinerary_plan"
    assert "planner" not in nodes
    assert "verifier" not in nodes
    assert "optional_critic" not in nodes
    assert "pre_ranker" in nodes
    assert "availability_checker" in nodes
    assert "post_check_filter" in nodes
    assert "final_ranker" in nodes
    assert all(query.limit >= 300 for query in result.compiled_recall_plan.queries)


def test_plan_payload_has_short_frontend_pros_cons() -> None:
    result = run_planning_request("周末和朋友出去玩四个小时，想唱歌吃饭，预算600元")
    plans = (result.response.response_payload or {}).get("plans", [])

    assert plans
    for plan in plans:
        assert {
            "plan_id",
            "title",
            "subtitle",
            "tags",
            "pros",
            "cons",
            "timeline",
            "route_text",
            "budget_text",
            "warnings",
            "score",
        } <= set(plan)
        assert 2 <= len(plan["pros"]) <= 4
        assert 1 <= len(plan["cons"]) <= 3
        assert all(len(item) <= 15 for item in plan["pros"])
        assert all(len(item) <= 15 for item in plan["cons"])


def test_indoor_quick_start_does_not_force_restaurant() -> None:
    understanding = resolve_intent("今天想安排室内活动，别太晒，路线轻松一点。", {}, {})
    constraints, recall = build_constraints(understanding, city="北京", origin=None)

    assert "restaurant" not in understanding.slots.required_slots
    assert "restaurant" not in understanding.poi_recall_intent.target_logical_categories
    assert all("restaurant" not in item.logical_categories for item in recall.slot_recall_requirements)
    assert "restaurant" not in constraints.hard_constraints.required_slots


def test_meal_keywords_allow_restaurant_but_cap_restaurant_slots() -> None:
    understanding = LLMUnderstanding(
        raw_user_message="下午吃饭再安排活动，晚点再吃个饭",
        intent=IntentResult(request_type="full_itinerary_plan"),
        slots={
            "required_slots": ["restaurant", "activity", "restaurant_or_cafe", "restaurant"],
        },
        poi_recall_intent={"target_logical_categories": ["restaurant", "activity"]},
    )

    constraints, recall = build_constraints(understanding, city="北京", origin=None)
    restaurant_query_count = sum(
        1
        for requirement in recall.slot_recall_requirements
        if "restaurant" in requirement.logical_categories
    )

    assert restaurant_query_count == 2
    assert ["restaurant", "activity", "restaurant_2"] == constraints.hard_constraints.required_slots


def test_explicit_time_crossing_meal_time_allows_restaurant() -> None:
    understanding = resolve_intent("今天下午4点开始玩3小时，帮我安排轻松一点。", {}, {})
    constraints, recall = build_constraints(understanding, city="北京", origin=None)

    assert any("restaurant" in item.logical_categories for item in recall.slot_recall_requirements)
    assert "restaurant" in constraints.soft_preferences.preferred_categories


def test_inspiration_prompt_becomes_must_poi() -> None:
    understanding = resolve_intent("我想去 天安门广场-国旗，帮我搭配一个本地生活方案。", {}, {})
    constraints, recall = build_constraints(understanding, city="北京", origin=None)
    compiled = compile_recall_plan(recall, constraints, create_planning_state("x").context.poi_logical_tag_catalog)

    assert understanding.intent.request_type == "full_itinerary_plan"
    assert "天安门广场-国旗" in understanding.poi_keyword_intent.must_poi_keywords
    assert "天安门广场" in understanding.poi_keyword_intent.must_poi_keywords
    assert compiled.must_poi_resolution.enabled is True
    assert "天安门广场" in compiled.must_poi_resolution.keywords
    attraction_queries = [query for query in compiled.queries if query.slot_id == "attraction"]
    assert attraction_queries
    assert {query.logical_category for query in attraction_queries} == {"attraction"}


def test_unresolved_inspiration_must_poi_gets_safe_fallback_candidate(monkeypatch) -> None:
    import app.graph.services as graph_services

    monkeypatch.setattr(
        graph_services.PoiRepository,
        "fetch_by_name_keywords",
        lambda self, keywords, categories=None: {category: [] for category in (categories or [])},
    )

    understanding = resolve_intent("我想去 天安门广场-国旗，帮我搭配一个本地生活方案。", {}, {})
    constraints, recall = build_constraints(understanding, city="北京", origin=None)
    compiled = compile_recall_plan(recall, constraints, create_planning_state("x").context.poi_logical_tag_catalog)
    raw, _stats = collect_candidates(compiled, constraints)

    must_items = [item for items in raw.values() for item in items if item.must_include]
    assert must_items
    assert any(item.recall_source == "user_must_fallback" for item in must_items)
    assert any("天安门广场" in item.name for item in must_items)


def test_quick_start_hotspots_and_budget_templates() -> None:
    hotspots = resolve_intent("帮我找几个北京热门的吃喝玩乐地点。", {}, {})
    budget = resolve_intent("想找今天比较划算、预算友好的活动和餐厅。", {}, {})

    assert hotspots.intent.request_type == "single_category_recommend"
    assert "restaurant" in hotspots.poi_recall_intent.target_logical_categories
    assert budget.intent.request_type == "full_itinerary_plan"
    assert {"activity", "entertainment", "restaurant"} & set(budget.poi_recall_intent.target_logical_categories)


def test_message_origin_overrides_current_geo_location(monkeypatch) -> None:
    import app.graph.services as graph_services

    monkeypatch.setattr(
        graph_services.PoiRepository,
        "fetch_by_name_keywords",
        lambda self, keywords, categories=None: {
            "poi_attractions": [
                {
                    "id": "origin_sanlitun",
                    "name": "三里屯",
                    "lat": 39.9365,
                    "lon": 116.4551,
                    "address": "北京市朝阳区三里屯",
                }
            ]
        },
    )

    understanding = resolve_intent("从三里屯出发，帮我安排两个室内活动。", {}, {})
    current_origin = OriginPoint(name="当前位置", lat=39.9, lng=116.4, source="browser_geolocation")
    constraints, _recall = build_constraints(understanding, city="北京", origin=current_origin)

    assert understanding.distance.origin_text == "三里屯"
    assert constraints.hard_constraints.origin is not None
    assert constraints.hard_constraints.origin.name == "三里屯"
    assert constraints.hard_constraints.origin.source == "user_message"
    assert constraints.hard_constraints.origin.lat == 39.9365


def test_current_geo_location_used_when_message_origin_unresolved(monkeypatch) -> None:
    import app.graph.services as graph_services

    monkeypatch.setattr(
        graph_services.PoiRepository,
        "fetch_by_name_keywords",
        lambda self, keywords, categories=None: {category: [] for category in (categories or [])},
    )

    understanding = resolve_intent("从不存在的起点出发，帮我安排两个室内活动。", {}, {})
    current_origin = OriginPoint(name="当前位置", lat=39.9, lng=116.4, source="browser_geolocation")
    constraints, _recall = build_constraints(understanding, city="北京", origin=current_origin)

    assert understanding.distance.origin_text == "不存在的起点"
    assert constraints.hard_constraints.origin == current_origin


def test_timeline_and_route_segments_start_from_origin() -> None:
    origin = OriginPoint(name="当前位置", lat=39.9, lng=116.4, source="browser_geolocation")
    plan = CandidatePlan(
        plan_id="plan_origin",
        generation_strategy="test",
        estimated_timeline=[
            TimelineItem(time_text="14:00-15:00", title="测试 POI", poi_id="poi_1"),
        ],
    )
    items = [
        {"id": "poi_1", "name": "测试 POI", "lat": 39.91, "lon": 116.41},
        {"id": "poi_2", "name": "第二站", "lat": 39.92, "lon": 116.42},
    ]

    timeline = _timeline_with_origin(plan, origin)
    segments = _route_segments_for_items(items, origin)

    assert timeline[0]["type"] == "origin"
    assert timeline[0]["title"] == "起点"
    assert "lat" not in timeline[0]
    assert "address" not in timeline[0]
    assert timeline[1]["title"] == "测试 POI"
    assert segments[0]["from_id"] == "origin"
    assert segments[0]["from"] == "起点"
    assert segments[0]["to"] == "测试 POI"
    assert segments[0]["from_type"] == "origin"
    assert segments[1]["from"] == "测试 POI"


def test_route_planner_filters_adjacent_pois_under_one_km() -> None:
    understanding = LLMUnderstanding(
        raw_user_message="安排两个活动",
        intent=IntentResult(request_type="full_itinerary_plan"),
        slots={"required_slots": ["activity", "shopping"]},
        poi_recall_intent={"target_logical_categories": ["activity", "shopping"]},
    )
    constraints, _recall = build_constraints(understanding, city="北京", origin=None)
    close_activity = ScoredPOICandidate(
        poi_id="a1",
        name="活动A",
        logical_category="activity",
        physical_table="poi_activities",
        lat=39.9000,
        lng=116.4000,
    )
    close_shopping = ScoredPOICandidate(
        poi_id="s1",
        name="购物B",
        logical_category="shopping",
        physical_table="poi_shoppings",
        lat=39.9005,
        lng=116.4005,
    )
    far_shopping = ScoredPOICandidate(
        poi_id="s2",
        name="购物C",
        logical_category="shopping",
        physical_table="poi_shoppings",
        lat=39.9300,
        lng=116.4300,
    )

    no_plan = create_route_plans({"activity": [close_activity], "shopping": [close_shopping]}, constraints)
    valid_plan = create_route_plans({"activity": [close_activity], "shopping": [far_shopping]}, constraints)

    assert no_plan == []
    assert valid_plan

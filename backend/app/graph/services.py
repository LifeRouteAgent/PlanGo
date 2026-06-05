from __future__ import annotations

import re
from itertools import product
from math import asin, cos, radians, sin, sqrt
from datetime import datetime, timedelta
from typing import Any

from app.agents.availability_checker import availability_checker_node as legacy_availability
from app.agents.intent_router import _detect_intent_type, _detect_target_categories
from app.agents.llm_understanding import build_llm_understanding
from app.agents.ranker import ranker_node as legacy_ranker
from app.agents.route_planner import route_time_planner_node as legacy_route_planner
from app.agents.verifier import verifier_node as legacy_verifier
from app.graph.state import (
    AvailabilityResults,
    BudgetPolicy,
    CandidatePlan,
    CategoryTagRequirement,
    CompiledRecallPlan,
    CompiledRecallQuery,
    DistancePolicy,
    ESNameMatchPlan,
    FallbackLevel,
    FallbackPolicy,
    FinalConstraints,
    HardConstraints,
    IntentResult,
    KeywordRecallPlan,
    LLMUnderstanding,
    LogicalRecallPlan,
    MustPOIResolutionPlan,
    OriginPoint,
    PHYSICAL_TABLES,
    PlanBudgetSummary,
    PlanRankFeatures,
    PlanSlot,
    POIAvailability,
    POIScoreBreakdown,
    QueryRecallStat,
    RankedPlan,
    RatingPolicy,
    RecallStats,
    SafePOICandidate,
    ScoredPOICandidate,
    SceneUnderstanding,
    SessionPreferenceProfile,
    SlotDetail,
    SlotRecallRequirement,
    SlotUnderstanding,
    SoftPreferences,
    TimePolicy,
    TimelineItem,
    VerifiedPlan,
    VerificationIssue,
)
from app.services.poi_repository import PoiRecallConstraints, PoiRepository
from app.services.poi_catalog_service import PoiCatalogService
from app.services.amap_route_service import AmapRouteService

LEGACY_TO_LOGICAL = {f"poi_{name}": name for name in PHYSICAL_TABLES}
SLOT_CATEGORIES = {
    "restaurant": ["restaurant"],
    "restaurant_2": ["restaurant"],
    "restaurant_or_cafe": ["restaurant"],
    "activity": ["activity", "attraction"],
    "attraction": ["attraction"],
    "activity_or_attraction": ["activity", "attraction"],
    "activity_or_entertainment": ["activity", "entertainment", "attraction"],
    "shopping": ["shopping"],
    "shopping_or_cafe": ["shopping", "restaurant"],
    "entertainment": ["entertainment"],
    "fitness": ["fitness"],
    "beauty": ["beauty"],
    "lifestyle": ["entertainment", "fitness", "beauty"],
    "beauty_or_spa": ["beauty"],
}
SCENE_SLOTS = {
    "family_half_day": (["activity_or_entertainment", "restaurant"], ["shopping_or_cafe"]),
    "friends_gathering": (["activity_or_entertainment", "restaurant"], ["lifestyle"]),
    "couple_date": (["activity_or_attraction", "restaurant"], ["restaurant_or_cafe"]),
    "meal_only": (["restaurant"], []),
    "meal_plus_activity": (["activity_or_entertainment", "restaurant"], []),
    "shopping_leisure": (["shopping", "restaurant_or_cafe"], []),
    "relaxation": (["beauty_or_spa", "restaurant_or_cafe"], []),
    "unknown": (["activity_or_entertainment", "restaurant"], []),
}
MEAL_KEYWORDS = (
    "吃饭", "吃喝", "餐厅", "餐馆", "美食", "午饭", "午餐", "晚饭", "晚餐",
    "早饭", "早餐", "下午茶", "咖啡", "轻食", "火锅", "烧烤", "甜品", "喝咖啡",
)
INSPIRATION_MUST_PATTERN = re.compile(r"我想去\s*(?P<name>.+?)\s*[，,]\s*帮我搭配")
ORIGIN_TEXT_PATTERNS = (
    re.compile(r"(?:从|由)\s*(?P<name>[^，,。；;]{2,24})\s*(?:出发|开始|过去|去|到)"),
    re.compile(r"(?:我在|人在|当前位置在|现在在)\s*(?P<name>[^，,。；;]{2,24})"),
    re.compile(r"(?P<name>[^，,。；;]{2,24})\s*(?:附近|周边)\s*(?:出发|开始|安排|找|推荐)"),
)


def resolve_intent(
    message: str,
    profile: dict[str, Any],
    context: dict[str, Any],
    *,
    poi_knowledge: dict[str, Any] | None = None,
) -> LLMUnderstanding:
    raw = build_llm_understanding(
        message,
        profile,
        conversation_context=context,
        poi_knowledge=poi_knowledge,
    ) or {}
    raw = _merge_rule_understanding(raw, _rule_understanding(message))
    catalog = _catalog_from_knowledge(poi_knowledge or {})
    rule_tag_matches = PoiCatalogService().match_query_tags(message, catalog)
    legacy_intent = str(raw.get("intent_type") or _detect_intent_type(message))
    request_type = {
        "capability": "simple_qa",
        "simple_qa": "simple_qa",
        "category_recommend": "single_category_recommend",
        "poi_search": "single_category_recommend",
        "full_trip_plan": "full_itinerary_plan",
    }.get(legacy_intent, "full_itinerary_plan")
    if context.get("has_active_plan") and _looks_like_adjustment(message):
        request_type = "plan_adjustment"
    categories = [
        LEGACY_TO_LOGICAL.get(item, item)
        for item in (raw.get("target_categories") or _detect_target_categories(message))
        if LEGACY_TO_LOGICAL.get(item, item) in PHYSICAL_TABLES
    ]
    if rule_tag_matches:
        categories = list(dict.fromkeys([*categories, *rule_tag_matches.keys()]))
        if request_type == "simple_qa":
            request_type = "single_category_recommend"
    scenario = str(raw.get("scenario") or _fallback_scene(message))
    meal_allowed = _should_include_restaurant(message, raw)
    categories = _normalize_restaurant_categories(categories, meal_allowed, request_type)
    required, optional = SCENE_SLOTS.get(scenario, SCENE_SLOTS["unknown"])
    raw_slots = list(
        raw.get("required_slots")
        or (categories if request_type == "single_category_recommend" and categories else required)
    )
    raw_slots = _normalize_restaurant_slots(raw_slots, meal_allowed)
    if not raw_slots and categories:
        raw_slots = list(categories)
    must_keywords = _dedupe([
        *[item.get("name") for item in raw.get("must_pois", []) if item.get("name")],
        *_must_poi_keywords_from_message(message),
    ])
    return LLMUnderstanding(
        raw_user_message=message,
        intent=IntentResult(
            request_type=request_type,
            is_followup=bool(context.get("has_active_plan")),
            adjustment_type=_adjustment_type(message) if request_type == "plan_adjustment" else None,
            confidence=0.8 if raw else 0.55,
        ),
        scene=SceneUnderstanding(
            scene_type=scenario,
            party_type=scenario.split("_", 1)[0] if scenario != "unknown" else "unknown",
            people_count=raw.get("people_count") or _people_count(message),
            has_child="孩子" in message or "亲子" in message,
        ),
        slots=SlotUnderstanding(
            required_slots=raw_slots,
            optional_slots=optional,
            slot_details=[
                SlotDetail(
                    slot_id=slot,
                    slot_name=slot,
                    required=True,
                    candidate_logical_categories=SLOT_CATEGORIES.get(slot, categories),
                )
                for slot in raw_slots
            ],
        ),
        poi_recall_intent={
            "target_logical_categories": categories,
            "category_tag_requirements": _category_tag_requirements(
                raw,
                poi_knowledge or {},
                rule_tag_matches=rule_tag_matches,
            ),
        },
        poi_keyword_intent={
            "must_poi_keywords": must_keywords,
            "avoid_poi_keywords": list(raw.get("avoid_tags", [])),
            "preference_poi_keywords": list(raw.get("preference_keywords", [])),
            "keyword_search_engine": "mysql_like",
        },
        budget={
            "total_budget": raw.get("budget") or _number_after(message, "预算"),
            "budget_is_explicit": bool(raw.get("budget") or "预算" in message),
        },
        distance={
            "distance_preference": "nearby" if any(x in message for x in ("附近", "别太远", "近一点")) else "normal",
            "origin_text": _extract_origin_text(message),
            "origin_source": "user_message" if _extract_origin_text(message) else None,
        },
        time={
            "duration_hours": raw.get("duration_hours") or _duration(message),
            "time_is_explicit": bool(raw.get("duration_hours") or _duration(message)),
        },
        rating={"min_rating": 4.0, "rating_preference": "normal"},
    )


def _category_tag_requirements(
    raw: dict[str, Any],
    poi_knowledge: dict[str, Any],
    *,
    rule_tag_matches: dict[str, dict[str, list[str]]] | None = None,
) -> list[CategoryTagRequirement]:
    categories = poi_knowledge.get("categories") if isinstance(poi_knowledge, dict) else {}
    available = {
        category: set(info.get("available_tags") or [])
        for category, info in (categories or {}).items()
        if isinstance(info, dict)
    }
    result: list[CategoryTagRequirement] = []
    for item in raw.get("category_tag_requirements", []) or []:
        if not isinstance(item, dict):
            continue
        category = LEGACY_TO_LOGICAL.get(str(item.get("logical_category") or ""), str(item.get("logical_category") or ""))
        if category not in available:
            continue
        positive = [str(tag) for tag in item.get("positive_logic_tags", []) if str(tag) in available[category]]
        negative = [str(tag) for tag in item.get("negative_logic_tags", []) if str(tag) in available[category]]
        if not positive and not negative:
            continue
        result.append(
            CategoryTagRequirement(
                logical_category=category,
                target_slot=str(item.get("target_slot") or category),
                positive_logic_tags=_dedupe(positive),
                negative_logic_tags=_dedupe(negative),
            )
        )
    existing = {requirement.logical_category for requirement in result}
    for category, matches in (rule_tag_matches or {}).items():
        if category in existing or category not in available:
            continue
        positive = [tag for tag in matches.get("positive", []) if tag in available[category]]
        negative = [tag for tag in matches.get("negative", []) if tag in available[category]]
        if positive or negative:
            result.append(
                CategoryTagRequirement(
                    logical_category=category,
                    target_slot=category,
                    positive_logic_tags=_dedupe(positive),
                    negative_logic_tags=_dedupe(negative),
                )
            )
    return result


def _rule_understanding(message: str) -> dict[str, Any]:
    """Deterministic understanding for frontend fixed prompts and inspiration cards."""

    must_keywords = _must_poi_keywords_from_message(message)
    if must_keywords:
        return {
            "intent_type": "full_trip_plan",
            "target_categories": ["poi_attraction", "poi_activity", "poi_entertainment", "poi_shopping"],
            "required_slots": ["attraction", "activity_or_entertainment"],
            "must_pois": [{"name": keyword, "category": "poi_attraction", "must_include": True} for keyword in must_keywords],
            "preference_keywords": [keyword for keyword in must_keywords if keyword],
            "scenario": "inspiration_must_poi",
        }

    if "我推荐附近适合今天去的本地生活地点" in message:
        return {
            "intent_type": "category_recommend",
            "target_categories": ["poi_activity", "poi_attraction", "poi_entertainment", "poi_shopping"],
            "required_slots": ["activity", "attraction", "entertainment", "shopping"],
            "preference_keywords": ["今天", "附近", "热门"],
            "scenario": "nearby_today",
        }
    if "北京热门的吃喝玩乐地点" in message:
        return {
            "intent_type": "category_recommend",
            "target_categories": ["poi_restaurant", "poi_activity", "poi_attraction", "poi_entertainment", "poi_shopping"],
            "required_slots": ["restaurant", "activity", "attraction", "entertainment", "shopping"],
            "preference_keywords": ["热门", "吃喝玩乐"],
            "scenario": "city_hotspots",
        }
    if "预算友好的活动和餐厅" in message or "比较划算" in message:
        return {
            "intent_type": "full_trip_plan",
            "target_categories": ["poi_activity", "poi_entertainment", "poi_restaurant"],
            "required_slots": ["activity_or_entertainment", "restaurant"],
            "preference_keywords": ["划算", "预算友好"],
            "scenario": "budget_activity_meal",
            "budget": 300,
        }
    if "室内活动" in message and ("别太晒" in message or "路线轻松" in message):
        return {
            "intent_type": "full_trip_plan",
            "target_categories": ["poi_activity", "poi_entertainment", "poi_shopping", "poi_beauty"],
            "required_slots": ["activity_or_entertainment", "shopping"],
            "preference_keywords": ["室内", "轻松", "不晒"],
            "scenario": "indoor_light_route",
        }
    return {}


def _merge_rule_understanding(raw: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    if not rule:
        return raw
    merged = dict(raw)
    for key, value in rule.items():
        if isinstance(value, list):
            if any(isinstance(item, dict) for item in value):
                merged[key] = _dedupe_dict_list([*value, *list(merged.get(key) or [])])
            else:
                merged[key] = _dedupe([*value, *list(merged.get(key) or [])])
        elif value not in (None, "", {}):
            merged[key] = value
    return merged


def _dedupe_dict_list(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _must_poi_keywords_from_message(message: str) -> list[str]:
    match = INSPIRATION_MUST_PATTERN.search(message)
    if not match:
        return []
    name = match.group("name").strip(" ，,。")
    if not name:
        return []
    variants = [name]
    for part in re.split(r"[-—–/｜|]", name):
        part = part.strip()
        if len(part) >= 2:
            variants.append(part)
    return _dedupe(variants)[:4]


def _extract_origin_text(message: str) -> str | None:
    for pattern in ORIGIN_TEXT_PATTERNS:
        match = pattern.search(message)
        if not match:
            continue
        name = _clean_origin_text(match.group("name"))
        if name:
            return name
    return None


def _clean_origin_text(value: str) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    text = text.strip(" ，,。；;：:")
    for prefix in ("我想", "帮我", "今天", "今晚", "下午", "上午", "中午"):
        if text.startswith(prefix) and len(text) > len(prefix) + 1:
            text = text[len(prefix):]
    for suffix in ("附近", "周边", "这边", "这里"):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[: -len(suffix)]
    if len(text) < 2:
        return ""
    return text[:24]


def _resolve_route_origin(origin_text: str | None, fallback: Any) -> Any:
    if not origin_text:
        return fallback
    resolved = _origin_from_name_search(origin_text)
    if resolved is not None:
        return resolved
    return fallback


def _origin_from_name_search(origin_text: str) -> OriginPoint | None:
    try:
        matches = PoiRepository(limit_per_category=3).fetch_by_name_keywords([origin_text])
    except Exception:
        return None
    for rows in matches.values():
        for row in rows:
            lat = _safe_float_value(row.get("lat"))
            lng = _safe_float_value(row.get("lon") or row.get("lng"))
            if lat is None or lng is None:
                continue
            row_name = str(row.get("name") or "")
            row_address = str(row.get("address") or "")
            return OriginPoint(
                name=origin_text,
                lat=lat,
                lng=lng,
                address=(" · ".join(part for part in (row_name, row_address) if part)) or None,
                source="user_message",
            )
    return None


def _safe_float_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _should_include_restaurant(message: str, raw: dict[str, Any]) -> bool:
    if any(keyword in message for keyword in MEAL_KEYWORDS):
        return True
    categories = [LEGACY_TO_LOGICAL.get(str(item), str(item)) for item in raw.get("target_categories", [])]
    slots = [str(item) for item in raw.get("required_slots", [])]
    if "restaurant" in categories and any(keyword in message for keyword in ("找几个", "推荐", "餐厅", "吃")):
        return True
    if any("restaurant" in slot or "餐" in slot for slot in slots) and any(keyword in message for keyword in MEAL_KEYWORDS):
        return True
    return _explicit_time_crosses_meal(message, raw)


def _explicit_time_crosses_meal(message: str, raw: dict[str, Any]) -> bool:
    window = _time_window_hours(message, raw)
    if not window:
        return False
    start, end = window
    if end <= start:
        end += 24
    return any(start < meal_hour < end for meal_hour in (12, 17, 18))


def _time_window_hours(message: str, raw: dict[str, Any]) -> tuple[float, float] | None:
    range_match = re.search(
        r"(?P<start>\d{1,2})(?:[:：]\d{1,2})?\s*点?.{0,4}(?:到|至|-|—|~)\s*(?P<end>\d{1,2})(?:[:：]\d{1,2})?\s*点?",
        message,
    )
    if range_match:
        start = _normalize_hour(float(range_match.group("start")), message[: range_match.start("start")])
        end = _normalize_hour(float(range_match.group("end")), message[range_match.start("end") - 4 : range_match.start("end")])
        return (start, end)
    start = _start_hour_from_message(message, raw.get("start_time"))
    duration = raw.get("duration_hours") or _duration(message)
    if start is not None and duration:
        return (start, start + float(duration))
    return None


def _start_hour_from_message(message: str, raw_start: Any) -> float | None:
    if isinstance(raw_start, str):
        match = re.search(r"(\d{1,2})(?::(\d{1,2}))?", raw_start)
        if match:
            return float(match.group(1)) + float(match.group(2) or 0) / 60
    match = re.search(r"(上午|中午|下午|晚上|今晚|今天)?\s*(\d{1,2})(?:[:：]\d{1,2})?\s*点", message)
    if not match:
        if "中午" in message:
            return 11.5
        if "下午" in message:
            return 14
        if "晚上" in message or "今晚" in message:
            return 18
        return None
    return _normalize_hour(float(match.group(2)), match.group(1) or "")


def _normalize_hour(hour: float, prefix: str) -> float:
    if any(token in prefix for token in ("下午", "晚上", "今晚")) and hour < 12:
        return hour + 12
    if "中午" in prefix and hour < 11:
        return hour + 12
    return hour


def _normalize_restaurant_categories(
    categories: list[str], meal_allowed: bool, request_type: str
) -> list[str]:
    if meal_allowed:
        return _dedupe(categories)
    if request_type == "single_category_recommend" and categories == ["restaurant"]:
        return categories
    return [category for category in _dedupe(categories) if category != "restaurant"]


def _normalize_restaurant_slots(slots: list[str], meal_allowed: bool) -> list[str]:
    result: list[str] = []
    restaurant_count = 0
    for slot in slots:
        slot_text = str(slot)
        is_restaurant_slot = slot_text in {"restaurant", "restaurant_2", "restaurant_or_cafe"} or "餐" in slot_text
        if is_restaurant_slot:
            if not meal_allowed or restaurant_count >= 2:
                continue
            restaurant_count += 1
            result.append("restaurant" if restaurant_count == 1 else "restaurant_2")
            continue
        result.append(slot_text)
    return _dedupe(result)


def _restaurant_allowed_for_understanding(understanding: LLMUnderstanding) -> bool:
    raw = {
        "target_categories": understanding.poi_recall_intent.target_logical_categories,
        "required_slots": understanding.slots.required_slots,
        "duration_hours": understanding.time.duration_hours,
        "start_time": (
            understanding.time.start_time.strftime("%H:%M")
            if understanding.time.start_time
            else None
        ),
    }
    return _should_include_restaurant(understanding.raw_user_message, raw)


def _catalog_from_knowledge(poi_knowledge: dict[str, Any]):
    from app.graph.state import POILogicalTagCatalog, POITableTagInfo

    tables = {}
    for category, info in (poi_knowledge.get("categories") or {}).items():
        if not isinstance(info, dict):
            continue
        tables[category] = POITableTagInfo(
            physical_table=str(info.get("physical_table") or PHYSICAL_TABLES.get(category, "")),
            logical_category=category,
            category_name=str(info.get("category_name") or category),
            filter_fields=list(info.get("filter_fields") or []),
            tag_fields=list(info.get("tag_fields") or []),
            supported_logic_tags=list(info.get("available_tags") or []),
            total_logic_tag_count=int(info.get("total_tag_count") or 0),
        )
    return POILogicalTagCatalog(tables=tables)


def build_constraints(
    understanding: LLMUnderstanding,
    *,
    city: str | None,
    origin: Any,
    previous: dict[str, Any] | None = None,
    session_preference: SessionPreferenceProfile | None = None,
) -> tuple[FinalConstraints, LogicalRecallPlan]:
    previous = previous or {}
    scene = understanding.scene.scene_type
    radii = {
        "family_half_day": (3, 5, 8),
        "friends_gathering": (6, 10, 15),
        "couple_date": (5, 8, 12),
        "meal_only": (3, 5, 8),
        "shopping_leisure": (5, 8, 12),
    }.get(scene, (5, 8, 12))
    if understanding.distance.distance_preference == "nearby":
        radii = tuple(max(2, round(value * 0.7, 1)) for value in radii)
    people = understanding.scene.people_count or 1
    total_budget = understanding.budget.total_budget
    per_person = understanding.budget.budget_per_person or (
        total_budget / people if total_budget else None
    )
    duration_minutes = round((understanding.time.duration_hours or 4.5) * 60)
    start_time = understanding.time.start_time or datetime.now().replace(
        hour=14, minute=0, second=0, microsecond=0
    )
    restaurant_allowed = _restaurant_allowed_for_understanding(understanding)
    required_slots = understanding.slots.required_slots or SCENE_SLOTS.get(scene, SCENE_SLOTS["unknown"])[0]
    required_slots = _normalize_restaurant_slots(required_slots, restaurant_allowed)
    preferred_categories = understanding.poi_recall_intent.target_logical_categories
    preferred_categories = _normalize_restaurant_categories(
        preferred_categories,
        restaurant_allowed,
        understanding.intent.request_type,
    )
    if not preferred_categories:
        preferred_categories = list(
            dict.fromkeys(
                category
                for slot in required_slots
                for category in SLOT_CATEGORIES.get(slot, ["activity", "restaurant"])
            )
        )
        preferred_categories = _normalize_restaurant_categories(
            preferred_categories,
            restaurant_allowed,
            understanding.intent.request_type,
        )
    positive_logic_tags = _dedupe([
        tag
        for requirement in understanding.poi_recall_intent.category_tag_requirements
        for tag in requirement.positive_logic_tags
    ])
    negative_logic_tags = _dedupe([
        tag
        for requirement in understanding.poi_recall_intent.category_tag_requirements
        for tag in requirement.negative_logic_tags
    ])
    avoid = _dedupe([
        *previous.get("avoid_keywords", []),
        *understanding.poi_keyword_intent.avoid_poi_keywords,
        *negative_logic_tags,
    ])
    preferences = _dedupe(
        [
            *previous.get("preference_keywords", []),
            *understanding.poi_keyword_intent.preference_poi_keywords,
        ]
    )
    if session_preference:
        preferred_categories = _dedupe([
            *preferred_categories,
            *session_preference.preferred_categories,
        ])
        positive_logic_tags = _dedupe([
            *positive_logic_tags,
            *session_preference.activity_preferences,
            *session_preference.dining_preferences,
            *session_preference.soft_preferences,
        ])
        negative_logic_tags = _dedupe([
            *negative_logic_tags,
            *session_preference.negative_preferences,
        ])
        avoid = _dedupe([
            *avoid,
            *session_preference.negative_preferences,
        ])
        preferences = _dedupe([
            *preferences,
            *session_preference.soft_preferences,
            *session_preference.activity_preferences,
            *session_preference.dining_preferences,
        ])
    route_origin = _resolve_route_origin(understanding.distance.origin_text, origin)
    constraints = FinalConstraints(
        hard_constraints=HardConstraints(
            city=city or previous.get("city") or "北京",
            origin=route_origin,
            avoid_keywords=avoid,
            required_slots=required_slots,
            max_total_duration_minutes=duration_minutes,
            max_route_minutes=90,
        ),
        soft_preferences=SoftPreferences(
            preferred_categories=preferred_categories,
            preference_keywords=preferences,
            liked_logic_tags=positive_logic_tags,
            disliked_logic_tags=negative_logic_tags,
        ),
        distance_policy=DistancePolicy(
            initial_radius_km=radii[0],
            fallback_radius_km=radii[1],
            max_radius_km=radii[2],
            max_pair_distance_km=radii[1],
            distance_score_policy={"near": 1.0, "fallback": 0.65, "far": 0.25},
        ),
        budget_policy=BudgetPolicy(
            budget_per_person=per_person,
            soft_upper_per_person=per_person * 1.3 if per_person else None,
            hard_upper_per_person=per_person * 1.8 if per_person else None,
            total_budget=total_budget,
            allow_unknown_price=True,
        ),
        time_policy=TimePolicy(
            start_time=start_time,
            return_home_time=start_time + timedelta(minutes=duration_minutes),
            duration_minutes=duration_minutes,
            meal_time_window={"lunch": ["11:00", "14:00"], "dinner": ["17:00", "21:00"]},
        ),
        rating_policy=RatingPolicy(),
        fallback_policy=FallbackPolicy(
            levels=[
                FallbackLevel(level=0, radius_km=radii[0], min_rating=4.0, price_multiplier=1.0),
                FallbackLevel(level=1, radius_km=radii[1], min_rating=3.8, price_multiplier=1.3),
                FallbackLevel(level=2, radius_km=radii[2], min_rating=3.8, price_multiplier=1.8),
            ]
        ),
        merge_policy_applied={
            "avoid_keywords": "append_dedupe",
            "preference_keywords": "append_dedupe",
            "budget": "explicit_override",
            "origin": "message_origin_or_explicit_or_default",
        },
    )
    requirements: list[SlotRecallRequirement] = []
    restaurant_query_count = 0
    for slot in required_slots:
        logical_categories = (
            [category for category in SLOT_CATEGORIES.get(slot, preferred_categories) if category in preferred_categories]
            or SLOT_CATEGORIES.get(slot, preferred_categories)
        )
        logical_categories = _normalize_restaurant_categories(
            logical_categories,
            restaurant_allowed,
            understanding.intent.request_type,
        )
        if "restaurant" in logical_categories:
            restaurant_query_count += 1
            if restaurant_query_count > 2:
                logical_categories = [category for category in logical_categories if category != "restaurant"]
        if not logical_categories:
            continue
        relevant_tags = [
            requirement
            for requirement in understanding.poi_recall_intent.category_tag_requirements
            if requirement.logical_category in logical_categories
            and requirement.target_slot in {slot, requirement.logical_category, ""}
        ]
        requirements.append(
            SlotRecallRequirement(
                slot_id=slot,
                logical_categories=logical_categories,
                positive_logic_tags=_dedupe([
                    tag for requirement in relevant_tags for tag in requirement.positive_logic_tags
                ]),
                negative_logic_tags=_dedupe([
                    tag for requirement in relevant_tags for tag in requirement.negative_logic_tags
                ]),
                limit=400,
            )
        )
    recall = LogicalRecallPlan(
        target_slots=required_slots,
        slot_recall_requirements=requirements,
        keyword_recall=KeywordRecallPlan(
            must_keywords=understanding.poi_keyword_intent.must_poi_keywords,
            preference_keywords=preferences,
            avoid_keywords=avoid,
        ),
    )
    return constraints, recall


def compile_recall_plan(
    logical: LogicalRecallPlan, constraints: FinalConstraints, catalog: Any
) -> CompiledRecallPlan:
    queries: list[CompiledRecallQuery] = []
    for requirement in logical.slot_recall_requirements:
        for category in requirement.logical_categories:
            if category not in PHYSICAL_TABLES or category not in catalog.tables:
                raise ValueError(f"unsupported logical_category: {category}")
            table = catalog.tables[category]
            limit = min(500, max(300, requirement.limit))
            queries.append(
                CompiledRecallQuery(
                    query_id=f"{requirement.slot_id}:{category}",
                    slot_id=requirement.slot_id,
                    logical_category=category,
                    physical_table=table.physical_table,
                    safe_return_fields=list(table.queryable_fields),
                    filters={
                        "radius_km": constraints.distance_policy.initial_radius_km,
                        "min_rating": constraints.rating_policy.min_rating_initial,
                        "avoid_keywords": constraints.hard_constraints.avoid_keywords,
                        "positive_logic_tags": requirement.positive_logic_tags,
                        "negative_logic_tags": requirement.negative_logic_tags,
                        "filter_fields": table.filter_fields,
                        "tag_fields": table.tag_fields,
                    },
                    es_name_match=ESNameMatchPlan(
                        enabled=bool(logical.keyword_recall.preference_keywords),
                        should_keywords=logical.keyword_recall.preference_keywords,
                        avoid_keywords=logical.keyword_recall.avoid_keywords,
                    ),
                    sort=list(table.default_sort),
                    limit=limit,
                )
            )
    return CompiledRecallPlan(
        queries=queries,
        must_poi_resolution=MustPOIResolutionPlan(
            enabled=bool(logical.keyword_recall.must_keywords),
            keywords=logical.keyword_recall.must_keywords,
        ),
    )


def collect_candidates(
    compiled: CompiledRecallPlan, constraints: FinalConstraints
) -> tuple[dict[str, list[SafePOICandidate]], RecallStats]:
    origin = constraints.hard_constraints.origin
    legacy_categories = list(dict.fromkeys(f"poi_{query.logical_category}" for query in compiled.queries))
    name_repository = PoiRepository(limit_per_category=80)
    must = (
        name_repository.fetch_by_name_keywords(
            compiled.must_poi_resolution.keywords, categories=legacy_categories
        )
        if compiled.must_poi_resolution.enabled
        else {}
    )
    must_found = any(items for items in must.values())
    hard_must_added = False
    result: dict[str, list[SafePOICandidate]] = {}
    stats: list[QueryRecallStat] = []
    for query in compiled.queries:
        legacy = f"poi_{query.logical_category}"
        repository = PoiRepository(limit_per_category=query.limit)
        recall_constraints = PoiRecallConstraints(
            origin_lat=origin.lat if origin else None,
            origin_lon=origin.lng if origin else None,
            radius_km=constraints.distance_policy.initial_radius_km,
            budget=constraints.budget_policy.total_budget,
            people_count=1,
            scene_type="v2",
            duration_hours=(constraints.time_policy.duration_minutes or 270) / 60,
            preference_keywords=tuple(_dedupe([
                *constraints.soft_preferences.preference_keywords,
                *query.filters.get("positive_logic_tags", []),
            ])),
            excluded_keywords=tuple(_dedupe([
                *constraints.hard_constraints.avoid_keywords,
                *query.filters.get("negative_logic_tags", []),
            ])),
        )
        rows = repository.fetch_by_categories([legacy], recall_constraints=recall_constraints)
        items = [*_safe_candidates(rows.get(legacy, []), query, False)]
        name_matches = _safe_candidates(must.get(legacy, []), query, False)
        if compiled.must_poi_resolution.enabled and not hard_must_added:
            if name_matches:
                anchor = name_matches[0].model_copy(
                    update={"must_include": True, "recall_source": "must_keyword"}
                )
                items.append(anchor)
                items.extend(name_matches[1:])
                hard_must_added = True
            elif not must_found:
                items.append(_synthetic_must_candidate(compiled.must_poi_resolution.keywords[0], query))
                hard_must_added = True
        else:
            items.extend(name_matches)
        items = list({item.poi_id: item for item in items}.values())
        result.setdefault(query.slot_id, []).extend(items)
        stats.append(QueryRecallStat(query_id=query.query_id, raw_count=len(items), after_hard_filter_count=len(items)))
    total = sum(len(items) for items in result.values())
    return result, RecallStats(by_query=stats, total_raw_count=total, total_after_filter_count=total)


def score_candidates(
    raw: dict[str, list[SafePOICandidate]], constraints: FinalConstraints, memory_tags: list[str]
) -> dict[str, list[ScoredPOICandidate]]:
    result: dict[str, list[ScoredPOICandidate]] = {}
    preference_keywords = constraints.soft_preferences.preference_keywords
    liked_tags = constraints.soft_preferences.liked_logic_tags
    floor = constraints.rating_policy.min_rating_floor
    for slot, items in raw.items():
        scored: list[ScoredPOICandidate] = []
        for item in items:
            if not item.must_include and item.rating is not None and item.rating < floor:
                continue
            quality = min(1, (item.rating or 4.0) / 5)
            distance = 0.65 if item.distance_km is None else max(
                0, 1 - item.distance_km / max(1, constraints.distance_policy.max_radius_km)
            )
            budget = _budget_score(item.avg_price, constraints.budget_policy.soft_upper_per_person)
            logic = _tag_overlap(item.logic_tags, liked_tags)
            keyword = _keyword_match(item, preference_keywords)
            memory = _tag_overlap(item.logic_tags, memory_tags)
            risk = (0.08 if item.avg_price is None else 0) + (0.06 if item.lat is None or item.lng is None else 0)
            final = 100 * (
                0.30 * distance
                + 0.30 * logic
                + 0.30 * keyword
                + 0.10 * quality
            ) + memory * 5 - risk * 100
            scored.append(
                ScoredPOICandidate(
                    **item.model_dump(),
                    final_poi_score=round(final, 2),
                    score_breakdown=POIScoreBreakdown(
                        quality_score=quality,
                        distance_score=distance,
                        budget_score=budget,
                        scene_score=keyword,
                        keyword_match_score=keyword,
                        logic_tag_match_score=logic,
                        memory_score=memory,
                        risk_penalty=risk,
                    ),
                    reasons=["综合评分、距离和预算适配"],
                    warnings=["价格未知"] if item.avg_price is None else [],
                )
            )
        result[slot] = sorted(scored, key=lambda item: item.final_poi_score, reverse=True)
    return result


def balance_candidates(scored: dict[str, list[ScoredPOICandidate]]) -> dict[str, list[ScoredPOICandidate]]:
    result: dict[str, list[ScoredPOICandidate]] = {}
    slot_count = max(1, len(scored))
    keep_limit = _balanced_keep_limit(slot_count)
    for slot, items in scored.items():
        must = [item for item in items if item.must_include]
        selected: list[ScoredPOICandidate] = list(must)
        seen: dict[tuple[str, str, str, str], int] = {}
        for item in items:
            band = "near" if (item.distance_km or 0) <= 3 else "mid" if (item.distance_km or 0) <= 8 else "far"
            key = (item.logical_category, item.subcategory or item.logical_category, _price_band(item.avg_price), band)
            if item in selected:
                continue
            if seen.get(key, 0) >= 4 and len(selected) < keep_limit * 0.75:
                continue
            selected.append(item)
            seen[key] = seen.get(key, 0) + 1
            if len(selected) >= keep_limit:
                break
        if len(selected) < keep_limit:
            selected_ids = {item.poi_id for item in selected}
            for item in items:
                if item.poi_id not in selected_ids:
                    selected.append(item)
                    selected_ids.add(item.poi_id)
                if len(selected) >= keep_limit:
                    break
        result[slot] = selected
    return result


def build_legacy_route_state(
    balanced: dict[str, list[ScoredPOICandidate]], constraints: FinalConstraints, query: str
) -> dict[str, Any]:
    recommended: dict[str, list[dict[str, Any]]] = {}
    for slot, items in balanced.items():
        recommended[slot] = [_legacy_scored(item) for item in items]
    start = constraints.time_policy.start_time or datetime.now()
    return {
        "user_query": query,
        "user_profile": {},
        "constraints": {
            "start_time": start.strftime("%H:%M"),
            "duration_hours": (constraints.time_policy.duration_minutes or 270) / 60,
            "duration_is_hard": True,
            "budget": constraints.budget_policy.total_budget or 600,
            "budget_is_hard": bool(constraints.budget_policy.total_budget),
            "max_route_minutes": constraints.hard_constraints.max_route_minutes or 90,
            "route_limit_is_hard": False,
        },
        "recommended_pois": recommended,
        "dag_plan": {
            "required_slots": constraints.hard_constraints.required_slots,
            "slot_sequence": constraints.hard_constraints.required_slots,
            "planning_template": "v2_slot_plan",
            "movement_policy": "balanced_local",
            "candidate_strategy": "slot_balance",
        },
        "errors": [],
        "candidate_plans": [],
        "verified_plans": [],
        "ranked_plans": [],
        "routes": [],
        "replanning_count": 1,
        "max_replanning_count": 1,
    }


def create_itineraries(legacy_state: dict[str, Any]) -> tuple[list[CandidatePlan], dict[str, Any]]:
    patch = legacy_route_planner(legacy_state)
    legacy_state.update(patch)
    plans = [_candidate_plan_from_legacy(plan) for plan in legacy_state.get("candidate_plans", [])]
    return plans, legacy_state


def check_availability(legacy_state: dict[str, Any]) -> tuple[AvailabilityResults, dict[str, Any]]:
    legacy_state.update(legacy_availability(legacy_state))
    by_poi: dict[str, POIAvailability] = {}
    for plan in legacy_state.get("candidate_plans", []):
        for item in plan.get("items", []):
            by_poi[str(item.get("id"))] = POIAvailability(
                open_status=str(item.get("open_status") or "unknown"),
                reservation_required=item.get("reservation_required"),
                queue_risk=item.get("crowd_risk"),
                source="database_or_rule",
            )
    return AvailabilityResults(by_poi=by_poi), legacy_state


def verify_plans(legacy_state: dict[str, Any]) -> tuple[list[VerifiedPlan], dict[str, Any]]:
    legacy_state.update(legacy_verifier(legacy_state))
    result: list[VerifiedPlan] = []
    for plan in legacy_state.get("candidate_plans", []):
        verified = next((x for x in legacy_state.get("verified_plans", []) if x.get("id") == plan.get("id")), None)
        issues = list((verified or {}).get("issues", []))
        blocks = [issue for issue in legacy_state.get("errors", []) if issue.get("severity") == "error"]
        result.append(
            VerifiedPlan(
                plan_id=str(plan.get("id")),
                passed=verified is not None,
                blocking_issues=[_verification_issue(issue, "block") for issue in blocks],
                warnings=[_verification_issue(issue, "warning") for issue in issues],
            )
        )
    return result, legacy_state


def rank_plans(legacy_state: dict[str, Any]) -> tuple[list[RankedPlan], dict[str, Any]]:
    legacy_state.update(legacy_ranker(legacy_state))
    result = [
        RankedPlan(
            plan_id=str(plan.get("id")),
            rank=index,
            plan_score=float(plan.get("plan_score", 0)),
            rank_label="首选" if index == 1 else "备选",
            rank_features=PlanRankFeatures(**{
                key: value for key, value in (plan.get("score_breakdown") or {}).items()
                if key in PlanRankFeatures.model_fields and isinstance(value, (int, float))
            }),
            why_ranked_high=["综合偏好、路线、时间和预算排序"],
            tradeoffs=[str(issue.get("message")) for issue in plan.get("issues", []) if issue.get("message")],
        )
        for index, plan in enumerate(legacy_state.get("ranked_plans", [])[:3], start=1)
    ]
    return result, legacy_state


def assemble_response(legacy_state: dict[str, Any], request_type: str) -> dict[str, Any]:
    plans = [_frontend_plan_card(plan) for plan in legacy_state.get("ranked_plans", [])[:3]]
    return {
        "response_type": "poi_list" if request_type == "single_category_recommend" else "plan_adjustment_result" if request_type == "plan_adjustment" else "plan_cards",
        "summary": "已根据你的需求生成推荐。" if plans else "暂时没有找到满足条件的方案。",
        "plans": plans,
        "selected_plan": plans[0] if plans else {},
        "followup_suggestions": ["换一批地点", "缩短距离", "调整预算"] if plans else ["放宽条件后重试"],
    }


def _safe_candidates(rows: list[dict[str, Any]], query: CompiledRecallQuery, must: bool) -> list[SafePOICandidate]:
    return [
        SafePOICandidate(
            poi_id=str(row.get("id")),
            name=str(row.get("name")),
            logical_category=query.logical_category,
            physical_table=query.physical_table,
            subcategory=row.get("subcategory"),
            logic_tags=_clean_logic_tags(row.get("tags", []), query.logical_category, row.get("subcategory")),
            address=row.get("address"),
            lat=row.get("lat"),
            lng=row.get("lon"),
            distance_km=row.get("distance_km"),
            rating=row.get("rating"),
            avg_price=row.get("avg_price"),
            image_url=_first_image_value(row.get("image_url"), row.get("images")),
            images=_image_list(row.get("images"), row.get("image_url")),
            recall_source="must_keyword" if must else "dynamic_sql",
            must_include=must,
            raw_extra={
                key: row.get(key)
                for key in ("open_status", "price_level")
                if row.get(key) is not None
            },
        )
        for row in rows
    ]


def _clean_logic_tags(values: Any, category: str, subcategory: Any = None, limit: int = 6) -> list[str]:
    result: list[str] = []
    candidates = list(values) if isinstance(values, list) else [values]
    if subcategory:
        candidates.insert(0, subcategory)
    for value in candidates:
        tag = _clean_tag_text(value)
        if not tag or tag in result:
            continue
        result.append(tag)
        if len(result) >= limit:
            break
    if not result:
        result.append(_category_label(category))
    return result


def _clean_tag_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if any(mark in text for mark in ("{", "}", "[", "]", "sub_category_id", "leaf_category_id", "category_id")):
        return ""
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ，,。；;：:|/\\")
    if text.lower() == "ktv":
        return "KTV"
    if any(mark in text for mark in (",", "，", ":", "：")):
        return ""
    if not text or len(text) > 15:
        return ""
    if text.lower() in {"activity", "attraction", "restaurant", "shopping", "entertainment", "fitness", "beauty", "mixed"}:
        return ""
    return text


def _category_label(category: str | None) -> str:
    return {
        "restaurant": "餐饮",
        "activity": "活动",
        "attraction": "景点",
        "shopping": "购物",
        "entertainment": "娱乐",
        "fitness": "运动",
        "beauty": "放松",
    }.get(str(category or ""), "本地生活")


def _image_list(images: Any, image_url: Any = None) -> list[str]:
    result: list[str] = []
    for value in [image_url, *(images if isinstance(images, list) else [images])]:
        if isinstance(value, dict):
            value = value.get("url") or value.get("src")
        text = str(value or "").strip().strip('"').strip("'")
        if text.startswith(("http://", "https://")) and text not in result:
            result.append(text)
    return result[:8]


def _first_image_value(image_url: Any, images: Any) -> str | None:
    values = _image_list(images, image_url)
    return values[0] if values else None


def _synthetic_must_candidate(name: str, query: CompiledRecallQuery) -> SafePOICandidate:
    safe_name = str(name or "用户指定地点").strip()[:80] or "用户指定地点"
    return SafePOICandidate(
        poi_id=f"user_must:{abs(hash((query.slot_id, safe_name))) % 10_000_000}",
        name=safe_name,
        logical_category=query.logical_category,
        physical_table=query.physical_table,
        subcategory=query.logical_category,
        logic_tags=["用户指定", "必去"],
        address="用户指定地点，数据库暂无详情",
        lat=None,
        lng=None,
        distance_km=None,
        rating=4.0,
        avg_price=None,
        recall_source="user_must_fallback",
        fallback_level=0,
        must_include=True,
        raw_extra={"open_status": "unknown"},
    )


def _legacy_scored(item: ScoredPOICandidate) -> dict[str, Any]:
    return {
        "id": item.poi_id, "name": item.name, "category": f"poi_{item.logical_category}",
        "subcategory": item.subcategory or item.logical_category, "lat": item.lat or 39.9042,
        "lon": item.lng or 116.4074, "address": item.address or "", "rating": item.rating or 4.0,
        "avg_price": item.avg_price, "price_level": "unknown", "open_status": "unknown",
        "tags": item.logic_tags, "image_url": item.image_url, "images": item.images,
        "score": item.final_poi_score / 20, "reason": "V2 Scorer 综合评分",
        "risk_flags": item.warnings, "estimated_duration_minutes": 90,
        "reservation_required": False, "crowd_risk": "unknown", "budget_fit": "unknown",
        "scene_fit": item.score_breakdown.scene_score, "distance_sensitive": True,
        "must_include": item.must_include,
    }


def _candidate_plan_from_legacy(plan: dict[str, Any]) -> CandidatePlan:
    return CandidatePlan(
        plan_id=str(plan.get("id")),
        generation_strategy=str(plan.get("candidate_strategy") or "slot_based"),
        slots=[
            PlanSlot(slot_id=str(item.get("category")), poi_id=str(item.get("id")), poi_name=str(item.get("name")))
            for item in plan.get("items", [])
        ],
        route_summary={
            "total_distance_km": plan.get("total_distance_km"),
            "total_route_minutes": plan.get("route_minutes"),
            "max_pair_distance_km": max([segment.get("distance_km", 0) for segment in plan.get("route_segments", [])] or [0]),
            "transport_mode": "mixed",
        },
        budget_summary=PlanBudgetSummary(
            estimated_total_budget=plan.get("estimated_budget"),
            budget_fit=str((plan.get("fit_summary") or {}).get("budget_fit") or "unknown"),
        ),
        estimated_timeline=[
            TimelineItem(time_text=str(item.get("time") or item.get("start_time") or ""), title=str(item.get("title") or item.get("name") or ""), poi_id=str(item.get("poi_id") or "") or None)
            for item in plan.get("timeline", [])
        ],
    )


def _safe_plan_card(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": plan.get("id"),
        "title": plan.get("title"),
        "tags": list(plan.get("highlight_tags", []))[:5],
        "timeline": plan.get("timeline", []),
        "route_text": f"总路程约 {plan.get('route_minutes', 0)} 分钟",
        "budget_text": f"预计预算约 {plan.get('estimated_budget', 0)} 元",
        "warnings": [issue.get("message") for issue in plan.get("issues", []) if issue.get("message")],
        "why_recommend": [plan.get("recommendation_reason") or "综合偏好、距离、时间和预算排序"],
        "items": [
            {"id": item.get("id"), "name": item.get("name"), "category": item.get("category"), "reason": item.get("reason")}
            for item in plan.get("items", [])
        ],
    }


def _frontend_plan_card(plan: dict[str, Any]) -> dict[str, Any]:
    items = [
        {
            key: item.get(key)
            for key in (
                "id", "name", "category", "subcategory", "lat", "lon", "address",
                "rating", "avg_price", "tags", "reason", "recommendation_reason",
                "reservation_required", "crowd_risk", "open_status", "risk_flags",
                "start_time", "end_time", "estimated_cost",
            )
            if item.get(key) is not None
        }
        for item in plan.get("items", [])
        if isinstance(item, dict)
    ]
    route_segments = [
        {
            key: segment.get(key)
            for key in (
                "from", "to", "from_id", "to_id", "from_item_id", "to_item_id",
                "distance_km", "duration_minutes", "transport_mode", "source", "polyline",
            )
            if segment.get(key) is not None
        }
        for segment in plan.get("route_segments", [])
        if isinstance(segment, dict)
    ]
    issues = [
        {
            key: issue.get(key)
            for key in ("code", "severity", "message", "suggestion", "source")
            if issue.get(key) is not None
        }
        for issue in plan.get("issues", [])
        if isinstance(issue, dict)
    ]
    return {
        "id": plan.get("id"),
        "plan_id": plan.get("id"),
        "title": plan.get("title"),
        "tags": list(plan.get("highlight_tags", []))[:5],
        "highlight_tags": list(plan.get("highlight_tags", []))[:5],
        "timeline": plan.get("timeline", []),
        "route_segments": route_segments,
        "total_distance_km": plan.get("total_distance_km"),
        "route_minutes": plan.get("route_minutes"),
        "total_duration_minutes": plan.get("total_duration_minutes"),
        "estimated_budget": plan.get("estimated_budget"),
        "fit_summary": plan.get("fit_summary", {}),
        "plan_score": plan.get("plan_score"),
        "score": plan.get("plan_score"),
        "score_breakdown": plan.get("score_breakdown", {}),
        "planning_template": plan.get("planning_template"),
        "movement_policy": plan.get("movement_policy"),
        "candidate_strategy": plan.get("candidate_strategy"),
        "route_text": f"总路程约 {plan.get('route_minutes', 0)} 分钟",
        "budget_text": f"预计预算约 {plan.get('estimated_budget', 0)} 元",
        "warnings": [issue.get("message") for issue in issues if issue.get("message")],
        "issues": issues,
        "recommendation_reason": plan.get("recommendation_reason") or "综合偏好、距离、时间和预算排序",
        "why_recommend": [plan.get("recommendation_reason") or "综合偏好、距离、时间和预算排序"],
        "pros": list(plan.get("pros", []))[:5],
        "cons": list(plan.get("cons", []))[:5],
        "items": items,
    }


def _verification_issue(issue: dict[str, Any], severity: str) -> VerificationIssue:
    return VerificationIssue(code=str(issue.get("code") or "unknown"), severity=severity, message=str(issue.get("message") or issue.get("code") or ""))


def create_route_plans(
    balanced: dict[str, list[ScoredPOICandidate]], constraints: FinalConstraints
) -> list[CandidatePlan]:
    slots = [slot for slot in constraints.hard_constraints.required_slots if balanced.get(slot)]
    if not slots:
        slots = [slot for slot, items in balanced.items() if items]
    if not slots:
        return []
    groups = [balanced[slot][:_route_combo_limit(len(slots))] for slot in slots]
    if any(not group for group in groups):
        return []
    must_ids = {
        item.poi_id
        for group in balanced.values()
        for item in group
        if item.must_include
    }

    plans: list[CandidatePlan] = []
    scanned = 0
    max_scan = 8000 if len(slots) >= 4 else 12000
    for combo in product(*groups):
        scanned += 1
        if scanned > max_scan or len(plans) >= 200:
            break
        items = list(combo)
        if must_ids and not must_ids.issubset({item.poi_id for item in items}):
            continue
        if _has_too_close_adjacent_pois(items):
            continue
        if _has_duplicate_place(items) or _has_semantic_duplicate(items):
            continue
        plan = _build_candidate_plan(len(plans) + 1, slots, items, constraints)
        if _route_plan_feasible(plan, items, constraints):
            plans.append(plan)
    return plans


def rank_route_plans(
    candidate_plans: list[CandidatePlan],
    scored: dict[str, list[ScoredPOICandidate]],
    constraints: FinalConstraints,
    *,
    availability: AvailabilityResults | None = None,
    top_n: int = 30,
) -> tuple[list[CandidatePlan], list[RankedPlan]]:
    item_index = _candidate_index(scored)
    ranked_pairs: list[tuple[CandidatePlan, RankedPlan]] = []
    for plan in candidate_plans:
        features = _plan_rank_features(plan, item_index, constraints, availability)
        score = round(
            100
            * (
                0.28 * features.preference_match
                + 0.18 * features.distance_reasonable
                + 0.14 * features.budget_fit
                + 0.14 * features.time_feasible
                + 0.12 * features.rating_heat
                + 0.08 * features.diversity_bonus
                + 0.06 * features.memory_fit
            )
            - features.warning_penalty * 20,
            2,
        )
        ranked_pairs.append(
            (
                plan,
                RankedPlan(
                    plan_id=plan.plan_id,
                    rank=0,
                    plan_score=max(0, score),
                    rank_label="candidate",
                    rank_features=features,
                    why_ranked_high=_plan_rank_reasons(features),
                    tradeoffs=_plan_tradeoffs(features),
                ),
            )
        )
    ranked_pairs.sort(key=lambda pair: pair[1].plan_score, reverse=True)
    selected_plans: list[CandidatePlan] = []
    ranked_plans: list[RankedPlan] = []
    selected_pairs: list[tuple[CandidatePlan, RankedPlan]] = []
    poi_usage: dict[str, int] = {}
    for plan, ranked in ranked_pairs:
        plan_pois = {slot.poi_id for slot in plan.slots}
        if top_n <= 3 and any(poi_usage.get(poi_id, 0) >= 1 for poi_id in plan_pois):
            continue
        selected_pairs.append((plan, ranked))
        for poi_id in plan_pois:
            poi_usage[poi_id] = poi_usage.get(poi_id, 0) + 1
        if len(selected_pairs) >= top_n:
            break
    if len(selected_pairs) < top_n:
        selected_ids = {plan.plan_id for plan, _ in selected_pairs}
        for plan, ranked in ranked_pairs:
            if plan.plan_id not in selected_ids:
                selected_pairs.append((plan, ranked))
                selected_ids.add(plan.plan_id)
            if len(selected_pairs) >= top_n:
                break
    for index, (plan, ranked) in enumerate(selected_pairs, start=1):
        ranked.rank = index
        ranked.rank_label = "top" if index == 1 else "backup"
        selected_plans.append(plan)
        ranked_plans.append(ranked)
    return selected_plans, ranked_plans


def check_plan_availability(
    candidate_plans: list[CandidatePlan],
    scored: dict[str, list[ScoredPOICandidate]],
) -> tuple[AvailabilityResults, list[CandidatePlan], dict[str, list[str]]]:
    item_index = _candidate_index(scored)
    by_poi: dict[str, POIAvailability] = {}
    filtered: list[CandidatePlan] = []
    warnings_by_plan: dict[str, list[str]] = {}
    for plan in candidate_plans:
        blocked = False
        warnings: list[str] = []
        for slot in plan.slots:
            item = item_index.get(slot.poi_id)
            if item is None:
                blocked = True
                warnings.append("poi_missing")
                continue
            availability = by_poi.get(item.poi_id) or _mock_availability(item)
            by_poi[item.poi_id] = availability
            if availability.open_status == "closed":
                blocked = True
                warnings.append(f"{item.name}:closed")
            elif availability.open_status == "open_unknown":
                warnings.append(f"{item.name}:open_unknown")
            if availability.reservation_required and availability.reservation_available is False:
                blocked = True
                warnings.append(f"{item.name}:reservation_unavailable")
            if availability.queue_risk == "high":
                blocked = True
                warnings.append(f"{item.name}:queue_high")
        if warnings:
            warnings_by_plan[plan.plan_id] = warnings
        if not blocked:
            filtered.append(plan)
    return AvailabilityResults(by_poi=by_poi), filtered, warnings_by_plan


def analyze_failure_reason(
    raw: dict[str, list[SafePOICandidate]],
    balanced: dict[str, list[ScoredPOICandidate]],
    candidate_plans: list[CandidatePlan],
    checked_plans: list[CandidatePlan],
    availability: AvailabilityResults,
) -> str:
    if any(not items for items in raw.values()):
        return "slot_candidate_insufficient"
    if any(not items for items in balanced.values()):
        return "tag_too_strict"
    if not candidate_plans:
        return "route_infeasible"
    failed_availability = [
        item for item in availability.by_poi.values()
        if item.open_status == "closed"
        or item.reservation_available is False
        or item.queue_risk == "high"
    ]
    if candidate_plans and not checked_plans and failed_availability:
        return "availability_failed"
    if len(checked_plans) < 3:
        return "category_diversity_insufficient"
    return "unknown"


def relax_constraints_for_failure(
    constraints: FinalConstraints, recall: LogicalRecallPlan, reason: str, iteration: int
) -> tuple[FinalConstraints, LogicalRecallPlan]:
    relaxed = constraints.model_copy(deep=True)
    relaxed_recall = recall.model_copy(deep=True)
    relaxed.distance_policy.initial_radius_km = min(
        max(relaxed.distance_policy.max_radius_km, relaxed.distance_policy.initial_radius_km * 1.5),
        30,
    )
    relaxed.distance_policy.max_pair_distance_km = min(
        max(relaxed.distance_policy.max_pair_distance_km * 1.35, relaxed.distance_policy.fallback_radius_km),
        30,
    )
    relaxed.rating_policy.min_rating_initial = max(
        relaxed.rating_policy.min_rating_floor,
        relaxed.rating_policy.min_rating_initial - 0.2,
    )
    if reason == "budget_too_strict" and relaxed.budget_policy.hard_upper_per_person:
        relaxed.budget_policy.hard_upper_per_person *= 1.25
        if relaxed.budget_policy.soft_upper_per_person:
            relaxed.budget_policy.soft_upper_per_person *= 1.15
    if reason in {"tag_too_strict", "slot_candidate_insufficient", "availability_failed"}:
        for requirement in relaxed_recall.slot_recall_requirements:
            requirement.limit = min(500, max(requirement.limit + 80, 400))
            if iteration >= 1:
                requirement.positive_logic_tags = requirement.positive_logic_tags[:1]
    if reason == "route_infeasible":
        relaxed.hard_constraints.max_route_minutes = int((relaxed.hard_constraints.max_route_minutes or 90) * 1.25)
    return relaxed, relaxed_recall


def assemble_state_response(state: Any) -> dict[str, Any]:
    request_type = state.llm_understanding.intent.request_type if state.llm_understanding else "full_itinerary_plan"
    item_index = _candidate_index(state.candidates.scored_candidates)
    ranked_by_id = {ranked.plan_id: ranked for ranked in state.plans.ranked_plans}
    ordered = [
        plan for plan in state.plans.candidate_plans
        if not ranked_by_id or plan.plan_id in ranked_by_id
    ]
    if ranked_by_id:
        order = {ranked.plan_id: ranked.rank for ranked in state.plans.ranked_plans}
        ordered.sort(key=lambda plan: order.get(plan.plan_id, 999))
    cards = [
        _state_plan_card(plan, ranked_by_id.get(plan.plan_id), item_index, state)
        for plan in ordered[:3]
    ]
    failure_reason = state.debug.recall_debug.get("failure_reason")
    return {
        "response_type": "plan_adjustment_result" if request_type == "plan_adjustment" else "plan_cards",
        "summary": "已生成可用方案。" if cards else "暂时没有足够可用方案。",
        "plans": cards,
        "selected_plan": cards[0] if cards else {},
        "failure_reason": failure_reason,
        "preference_context": _preference_context_payload(state),
        "warnings": [f"方案不足原因：{failure_reason}"] if failure_reason and len(cards) < 3 else [],
        "followup_suggestions": ["换一批地点", "放宽距离", "调整预算"] if cards else ["放宽距离或预算"],
    }


def _preference_context_payload(state: Any) -> dict[str, Any]:
    session = state.context.session_preference_profile
    memory = state.context.user_preference_profile
    similar_profiles = [
        {
            "cluster_id": cluster.cluster_id,
            "core_tags": cluster.core_tags,
            "similarity_score": cluster.similarity_score,
        }
        for cluster in memory.positive_clusters[:3]
    ]
    return {
        "priority": [
            "current_hard_constraints",
            "current_soft_preferences",
            "long_term_memory",
            "similar_user_preferences",
            "default_popularity",
        ],
        "session_profile": session.model_dump(mode="json"),
        "long_term_tags": [tag.tag_name for tag in memory.positive_tags[:12]],
        "negative_memory_tags": [tag.tag_name for tag in memory.negative_tags[:12]],
        "similar_profiles": similar_profiles,
    }


def _keyword_match(item: SafePOICandidate, keywords: list[str]) -> float:
    if not keywords:
        return 0.7
    text = " ".join(
        str(value or "")
        for value in [item.name, item.subcategory, item.address, " ".join(item.logic_tags)]
    ).lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in text) / len(keywords)


def _balanced_keep_limit(slot_count: int) -> int:
    if slot_count <= 1:
        return 150
    if slot_count == 2:
        return 80
    return 100


def _route_combo_limit(slot_count: int) -> int:
    if slot_count <= 2:
        return 40
    if slot_count == 3:
        return 30
    return 20


def _price_band(price: float | None) -> str:
    if price is None or price <= 0:
        return "unknown"
    if price < 80:
        return "low"
    if price < 200:
        return "mid"
    return "high"


def _has_duplicate_place(items: list[ScoredPOICandidate]) -> bool:
    seen: set[str] = set()
    for item in items:
        key = "|".join([item.poi_id, (item.name or "").strip().lower(), (item.address or "").strip().lower()])
        if key in seen:
            return True
        seen.add(key)
    return False


def _has_semantic_duplicate(items: list[ScoredPOICandidate]) -> bool:
    seen: set[tuple[str, str]] = set()
    seen_semantic: set[str] = set()
    for item in items:
        key = (item.logical_category, (item.subcategory or item.logical_category).strip().lower())
        if key in seen:
            return True
        seen.add(key)
        semantic_keys = _semantic_keys(item)
        if seen_semantic.intersection(semantic_keys):
            return True
        seen_semantic.update(semantic_keys)
    return False


def _has_too_close_adjacent_pois(items: list[ScoredPOICandidate], min_distance_km: float = 1.0) -> bool:
    for previous, current in zip(items, items[1:], strict=False):
        if previous.lat is None or previous.lng is None or current.lat is None or current.lng is None:
            continue
        distance = _haversine_km((previous.lat, previous.lng), (current.lat, current.lng))
        if distance < min_distance_km:
            return True
    return False


def _semantic_keys(item: ScoredPOICandidate) -> set[str]:
    generic = {
        "restaurant", "entertainment", "activity", "shopping", "fitness", "beauty",
        "餐饮服务", "餐饮相关", "餐厅美食", "体育休闲服务", "娱乐场所", "运动场馆",
    }
    keys: set[str] = set()
    for value in [item.subcategory, *item.logic_tags]:
        text = str(value or "").strip()
        if not text or text in generic:
            continue
        lowered = text.lower()
        if "ktv" in lowered:
            keys.add("ktv")
        elif "电影" in text or "cinema" in lowered or "影院" in text:
            keys.add("cinema")
        elif "棋牌" in text or "麻将" in text:
            keys.add("chess")
        elif "火锅" in text:
            keys.add("hotpot")
        elif "咖啡" in text:
            keys.add("coffee")
        elif len(text) <= 12:
            keys.add(lowered)
    return keys


def _build_candidate_plan(
    index: int,
    slots: list[str],
    items: list[ScoredPOICandidate],
    constraints: FinalConstraints,
) -> CandidatePlan:
    route_minutes, total_distance, max_pair = _route_metrics(items, constraints)
    visit_minutes = [_duration_for_category(item.logical_category) for item in items]
    estimated_budget = sum(float(item.avg_price or 0) for item in items)
    start = constraints.time_policy.start_time or datetime.now().replace(hour=14, minute=0, second=0, microsecond=0)
    cursor = start
    plan_slots: list[PlanSlot] = []
    timeline: list[TimelineItem] = []
    route_gap = round(route_minutes / max(1, len(items) - 1)) if len(items) > 1 else 0
    for slot, item, duration in zip(slots, items, visit_minutes, strict=False):
        end = cursor + timedelta(minutes=duration)
        plan_slots.append(
            PlanSlot(
                slot_id=slot,
                poi_id=item.poi_id,
                poi_name=item.name,
                start_time=cursor,
                end_time=end,
                duration_minutes=duration,
            )
        )
        timeline.append(
            TimelineItem(
                time_text=f"{cursor.strftime('%H:%M')}-{end.strftime('%H:%M')}",
                title=item.name,
                description=item.subcategory or item.logical_category,
                poi_id=item.poi_id,
            )
        )
        cursor = end + timedelta(minutes=route_gap)
    return CandidatePlan(
        plan_id=f"v2_plan_{index}",
        generation_strategy="slot_combo_v2",
        slots=plan_slots,
        route_summary={
            "total_distance_km": round(total_distance, 2),
            "total_route_minutes": route_minutes,
            "max_pair_distance_km": round(max_pair, 2),
            "transport_mode": "mixed",
        },
        budget_summary=PlanBudgetSummary(
            estimated_total_budget=round(estimated_budget, 2),
            estimated_per_person=round(estimated_budget, 2),
            budget_fit=_budget_fit_label(estimated_budget, constraints),
        ),
        estimated_timeline=timeline,
    )


def _route_plan_feasible(
    plan: CandidatePlan, items: list[ScoredPOICandidate], constraints: FinalConstraints
) -> bool:
    route_minutes = plan.route_summary.total_route_minutes or 0
    visit_minutes = sum(slot.duration_minutes or 0 for slot in plan.slots)
    max_total = constraints.hard_constraints.max_total_duration_minutes or 270
    if visit_minutes + route_minutes > max_total * 1.4:
        return False
    max_pair = plan.route_summary.max_pair_distance_km or 0
    if max_pair > max(20, constraints.distance_policy.max_pair_distance_km * 2):
        return False
    total_budget = constraints.budget_policy.total_budget
    estimated = plan.budget_summary.estimated_total_budget or 0
    if total_budget and estimated > total_budget * 1.8:
        return False
    return True


def _route_metrics(
    items: list[ScoredPOICandidate], constraints: FinalConstraints
) -> tuple[int, float, float]:
    points: list[tuple[float, float]] = []
    if constraints.hard_constraints.origin:
        points.append((constraints.hard_constraints.origin.lat, constraints.hard_constraints.origin.lng))
    points.extend((item.lat, item.lng) for item in items if item.lat is not None and item.lng is not None)
    if len(points) < 2:
        return 0, 0.0, 0.0
    distances = [_haversine_km(a, b) for a, b in zip(points, points[1:], strict=False)]
    total_distance = sum(distances)
    route_minutes = sum(max(5, round(distance * 3 + 5)) for distance in distances)
    return int(route_minutes), total_distance, max(distances or [0])


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    start_lat = radians(lat1)
    end_lat = radians(lat2)
    value = sin(d_lat / 2) ** 2 + cos(start_lat) * cos(end_lat) * sin(d_lon / 2) ** 2
    return 6371 * 2 * asin(sqrt(value))


def _duration_for_category(category: str) -> int:
    return {
        "restaurant": 75,
        "activity": 120,
        "attraction": 120,
        "shopping": 90,
        "entertainment": 120,
        "fitness": 90,
        "beauty": 90,
    }.get(category, 90)


def _budget_fit_label(estimated: float, constraints: FinalConstraints) -> str:
    total = constraints.budget_policy.total_budget
    if not total:
        return "unknown"
    if estimated <= total:
        return "good"
    if estimated <= total * 1.3:
        return "slightly_over"
    return "over"


def _candidate_index(scored: dict[str, list[ScoredPOICandidate]]) -> dict[str, ScoredPOICandidate]:
    return {item.poi_id: item for group in scored.values() for item in group}


def _plan_rank_features(
    plan: CandidatePlan,
    item_index: dict[str, ScoredPOICandidate],
    constraints: FinalConstraints,
    availability: AvailabilityResults | None,
) -> PlanRankFeatures:
    items = [item_index[slot.poi_id] for slot in plan.slots if slot.poi_id in item_index]
    if not items:
        return PlanRankFeatures(warning_penalty=1)
    avg_score = sum(item.final_poi_score for item in items) / max(1, len(items)) / 100
    distance = 1 - min(1, (plan.route_summary.total_route_minutes or 0) / max(1, constraints.hard_constraints.max_route_minutes or 90))
    total_minutes = sum(slot.duration_minutes or 0 for slot in plan.slots) + (plan.route_summary.total_route_minutes or 0)
    time_fit = 1 - min(1, total_minutes / max(1, (constraints.hard_constraints.max_total_duration_minutes or 270) * 1.4))
    budget_fit = {"good": 1.0, "unknown": 0.75, "slightly_over": 0.55, "over": 0.2}.get(plan.budget_summary.budget_fit, 0.6)
    rating = sum((item.rating or 4.0) / 5 for item in items) / max(1, len(items))
    diversity = len({(item.logical_category, item.subcategory) for item in items}) / max(1, len(items))
    warning = 0.0
    if availability:
        for item in items:
            poi_availability = availability.by_poi.get(item.poi_id)
            if poi_availability and poi_availability.open_status == "open_unknown":
                warning += 0.05
    return PlanRankFeatures(
        preference_match=avg_score,
        slot_coverage=len(items) / max(1, len(plan.slots)),
        distance_reasonable=max(0, distance),
        time_feasible=max(0, time_fit),
        rating_heat=rating,
        budget_fit=budget_fit,
        scene_fit=avg_score,
        memory_fit=sum(item.score_breakdown.memory_score for item in items) / max(1, len(items)),
        warning_penalty=min(1, warning),
        diversity_bonus=diversity,
    )


def _plan_rank_reasons(features: PlanRankFeatures) -> list[str]:
    reasons: list[str] = []
    if features.preference_match >= 0.7:
        reasons.append("偏好匹配")
    if features.distance_reasonable >= 0.6:
        reasons.append("距离合理")
    if features.budget_fit >= 0.75:
        reasons.append("预算合适")
    if features.diversity_bonus >= 0.9:
        reasons.append("类型丰富")
    return reasons or ["综合排序靠前"]


def _plan_tradeoffs(features: PlanRankFeatures) -> list[str]:
    tradeoffs: list[str] = []
    if features.warning_penalty:
        tradeoffs.append("营业需复核")
    if features.budget_fit < 0.6:
        tradeoffs.append("预算偏高")
    if features.distance_reasonable < 0.4:
        tradeoffs.append("路程偏长")
    return tradeoffs


def _mock_availability(item: ScoredPOICandidate) -> POIAvailability:
    raw_open = str(item.raw_extra.get("open_status") or "unknown").lower()
    open_status = "open_unknown" if raw_open in {"", "unknown", "none"} else raw_open
    if open_status not in {"open", "closed", "open_unknown"}:
        open_status = "open"
    seed = sum(ord(char) for char in item.poi_id + item.name)
    reservation_required = item.logical_category in {"restaurant", "activity", "entertainment", "beauty"} or (item.rating or 0) >= 4.6
    reservation_available = None if not reservation_required else seed % 53 != 0
    queue_risk = "high" if seed % 41 == 0 else "medium" if (item.rating or 0) >= 4.7 else "low"
    ticket_available = "available"
    table_available = "available" if item.logical_category == "restaurant" else None
    if reservation_required and reservation_available is False:
        if item.logical_category == "restaurant":
            table_available = "unavailable"
        else:
            ticket_available = "unavailable"
    return POIAvailability(
        open_status=open_status,
        reservation_required=reservation_required,
        reservation_available=reservation_available,
        queue_risk=queue_risk,
        ticket_available=ticket_available,
        table_available=table_available,
        source="mock_availability_v2",
    )


def _state_plan_card(
    plan: CandidatePlan,
    ranked: RankedPlan | None,
    item_index: dict[str, ScoredPOICandidate],
    state: Any,
) -> dict[str, Any]:
    items = [_state_item_card(slot, item_index.get(slot.poi_id), state) for slot in plan.slots]
    origin = state.constraints.hard_constraints.origin if state.constraints else None
    timeline = _timeline_with_origin(plan, origin)
    warnings = list(state.debug.recall_debug.get("availability_plan_warnings", {}).get(plan.plan_id, []))
    score = ranked.plan_score if ranked else 0
    tags = _short_points(
        [
            tag
            for item in items
            for tag in _clean_logic_tags(item.get("tags", []), str(item.get("logical_category") or ""), item.get("subcategory"), limit=2)
        ],
        5,
    )
    return {
        "id": plan.plan_id,
        "plan_id": plan.plan_id,
        "title": _plan_title(plan, items, ranked),
        "subtitle": _plan_subtitle(plan),
        "tags": tags,
        "highlight_tags": tags,
        "pros": _short_points(_plan_pros(plan, ranked, items), 4),
        "cons": _short_points(_plan_cons(plan, warnings, items), 3),
        "timeline": timeline,
        "route_segments": _route_segments_for_items(items, origin),
        "route_text": f"交通约 {plan.route_summary.total_route_minutes or 0} 分钟",
        "budget_text": f"预计约 {int(plan.budget_summary.estimated_total_budget or 0)} 元",
        "warnings": warnings,
        "score": score,
        "plan_score": score,
        "rank_features": ranked.rank_features.model_dump(mode="json") if ranked else {},
        "why_recommend": ranked.why_ranked_high if ranked else [],
        "tradeoffs": ranked.tradeoffs if ranked else [],
        "items": items,
        "total_distance_km": plan.route_summary.total_distance_km,
        "route_minutes": plan.route_summary.total_route_minutes,
        "total_duration_minutes": sum(slot.duration_minutes or 0 for slot in plan.slots) + (plan.route_summary.total_route_minutes or 0),
        "estimated_budget": plan.budget_summary.estimated_total_budget,
        "fit_summary": {"budget_fit": plan.budget_summary.budget_fit},
    }


def _timeline_with_origin(plan: CandidatePlan, origin: OriginPoint | None) -> list[dict[str, Any]]:
    timeline = [item.model_dump(mode="json") for item in plan.estimated_timeline]
    if origin is None:
        return timeline
    first_time = timeline[0].get("time_text", "") if timeline else ""
    start_text = str(first_time).split("-", 1)[0] if first_time else ""
    origin_item = {
        "time_text": start_text,
        "title": "起点",
        "description": "出发起点",
        "poi_id": None,
        "type": "origin",
        "source": origin.source,
    }
    return [origin_item, *timeline]


def _state_item_card(slot: PlanSlot, item: ScoredPOICandidate | None, state: Any) -> dict[str, Any]:
    if item is None:
        return {"id": slot.poi_id, "name": slot.poi_name}
    availability = state.plans.availability_results.by_poi.get(item.poi_id)
    return {
        "id": item.poi_id,
        "name": item.name,
        "category": f"poi_{item.logical_category}",
        "logical_category": item.logical_category,
        "subcategory": item.subcategory,
        "lat": item.lat,
        "lon": item.lng,
        "address": item.address,
        "rating": item.rating,
        "avg_price": item.avg_price,
        "image_url": item.image_url,
        "images": item.images,
        "tags": _clean_logic_tags(item.logic_tags, item.logical_category, item.subcategory, limit=8),
        "display_category": _category_label(item.logical_category),
        "reason": "、".join(item.reasons[:2]),
        "score": item.final_poi_score,
        "reservation_required": availability.reservation_required if availability else None,
        "reservation_available": availability.reservation_available if availability else None,
        "crowd_risk": availability.queue_risk if availability else None,
        "open_status": availability.open_status if availability else "unknown",
        "risk_flags": item.warnings,
        "start_time": slot.start_time.strftime("%H:%M") if slot.start_time else None,
        "end_time": slot.end_time.strftime("%H:%M") if slot.end_time else None,
    }


def _plan_title(plan: CandidatePlan, items: list[dict[str, Any]], ranked: RankedPlan | None) -> str:
    names = [str(item.get("name") or "") for item in items if item.get("name")]
    if len(names) >= 2:
        return f"{names[0]} + {names[1]}"
    return names[0] if names else f"方案 {ranked.rank if ranked else ''}".strip()


def _plan_subtitle(plan: CandidatePlan) -> str:
    return f"{len(plan.slots)}站 · {plan.route_summary.total_route_minutes or 0}分钟交通"


def _plan_pros(plan: CandidatePlan, ranked: RankedPlan | None, items: list[dict[str, Any]]) -> list[str]:
    pros = list(ranked.why_ranked_high if ranked else [])
    if plan.route_summary.total_route_minutes is not None:
        pros.append("路线清楚")
    if all((item.get("rating") or 0) >= 4.0 for item in items):
        pros.append("评分稳定")
    if plan.budget_summary.budget_fit in {"good", "unknown"}:
        pros.append("预算可控")
    return pros or ["匹配需求"]


def _plan_cons(plan: CandidatePlan, warnings: list[str], items: list[dict[str, Any]]) -> list[str]:
    cons: list[str] = []
    if warnings:
        cons.append("需复核状态")
    if any(item.get("reservation_required") for item in items):
        cons.append("建议预约")
    if plan.budget_summary.budget_fit == "slightly_over":
        cons.append("预算略高")
    if not cons:
        cons.append("营业待确认")
    return cons


def _short_points(values: list[Any], limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = text[:15]
        if text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _route_segments_for_items(items: list[dict[str, Any]], origin: OriginPoint | None = None) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    route_service = AmapRouteService()
    if origin is not None and items:
        first = items[0]
        segments.append(
            _route_segment_between(
                {
                    "id": "origin",
                    "name": "起点",
                    "lat": origin.lat,
                    "lon": origin.lng,
                },
                first,
                route_service,
                from_type="origin",
                to_type="poi",
            )
        )
    for start, end in zip(items, items[1:], strict=False):
        if not start or not end:
            continue
        segments.append(_route_segment_between(start, end, route_service, from_type="poi", to_type="poi"))
    return segments


def _route_segment_between(
    start: dict[str, Any],
    end: dict[str, Any],
    route_service: AmapRouteService,
    *,
    from_type: str,
    to_type: str,
) -> dict[str, Any]:
    start_lat = _safe_float_value(start.get("lat"))
    start_lng = _safe_float_value(start.get("lon") or start.get("lng"))
    end_lat = _safe_float_value(end.get("lat"))
    end_lng = _safe_float_value(end.get("lon") or end.get("lng"))
    distance = None
    duration = None
    source = "haversine_fallback"
    polyline: list[dict[str, float]] = []
    if start_lat is not None and start_lng is not None and end_lat is not None and end_lng is not None:
        fallback_distance = round(_haversine_km((start_lat, start_lng), (end_lat, end_lng)), 2)
        distance = fallback_distance
        duration = _route_duration_minutes(distance)
        polyline = [{"lat": start_lat, "lng": start_lng}, {"lat": end_lat, "lng": end_lng}]
        estimate = route_service.estimate_segment(
            {"id": start.get("id"), "name": start.get("name"), "lat": start_lat, "lon": start_lng},
            {"id": end.get("id"), "name": end.get("name"), "lat": end_lat, "lon": end_lng},
            fallback_distance_km=fallback_distance,
        )
        if estimate:
            distance = round(estimate.distance_km, 2)
            duration = estimate.duration_minutes
            source = estimate.source
            if estimate.polyline:
                polyline = estimate.polyline
    return {
        "from": start.get("name"),
        "to": end.get("name"),
        "from_id": start.get("id"),
        "to_id": end.get("id"),
        "from_item_id": start.get("id"),
        "to_item_id": end.get("id"),
        "from_type": from_type,
        "to_type": to_type,
        "distance_km": distance,
        "duration_minutes": duration,
        "transport_mode": _transport_mode(distance),
        "source": source,
        "polyline": polyline,
    }


def _route_duration_minutes(distance: float | None) -> int | None:
    if distance is None:
        return None
    return max(5, round(distance * 3 + 5))


def _transport_mode(distance: float | None) -> str:
    if distance is None:
        return "推荐交通"
    if distance <= 1.2:
        return "步行"
    if distance <= 8:
        return "打车"
    return "驾车"


def _fallback_scene(message: str) -> str:
    if "亲子" in message or "孩子" in message:
        return "family_half_day"
    if any(x in message for x in ("情侣", "对象", "约会")):
        return "couple_date"
    if any(x in message for x in ("朋友", "同事", "同学", "闺蜜")):
        return "friends_gathering"
    return "unknown"


def _looks_like_adjustment(message: str) -> bool:
    return any(x in message for x in ("换", "改", "保留", "不要", "太远", "太贵", "重新排序"))


def _adjustment_type(message: str) -> str:
    if "换" in message:
        return "replace_slot"
    if "太贵" in message or "便宜" in message:
        return "lower_budget"
    if "太远" in message or "近" in message:
        return "nearer"
    if "不要" in message:
        return "avoid_category"
    return "rerank"


def _people_count(message: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:个)?人", message)
    return int(match.group(1)) if match else None


def _duration(message: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:个)?小时", message)
    return float(match.group(1)) if match else None


def _number_after(message: str, prefix: str) -> float | None:
    match = re.search(prefix + r"[^\d]{0,5}(\d+(?:\.\d+)?)", message)
    return float(match.group(1)) if match else None


def _budget_score(price: float | None, soft_upper: float | None) -> float:
    if price is None or soft_upper is None:
        return 0.65
    return 1.0 if price <= soft_upper else max(0, 1 - (price - soft_upper) / max(1, soft_upper))


def _tag_overlap(tags: list[str], desired: list[str]) -> float:
    if not desired:
        return 0.7
    text = " ".join(tags)
    return sum(1 for tag in desired if tag in text) / len(desired)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))

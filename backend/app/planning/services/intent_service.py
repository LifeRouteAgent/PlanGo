from __future__ import annotations

import re
from itertools import product
from math import asin, cos, radians, sin, sqrt
from datetime import datetime, timedelta
from typing import Any

from app.planning.intent_rules import detect_intent_type, detect_target_categories
from app.agents.intent_agent import build_llm_understanding
from app.planning.state import (
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
)
from app.repositories.poi_repository import PoiRecallConstraints, PoiRepository
from app.planning.poi_catalog_service import PoiCatalogService
from app.integrations.amap_route_service import AmapRouteService
from app.planning.scoring_service import score_candidates as score_poi_candidates
from app.planning.payloads import normalize_response_payload

from app.planning.services.common import *


def resolve_intent(
    message: str,
    profile: dict[str, Any],
    context: dict[str, Any],
    *,
    poi_knowledge: dict[str, Any] | None = None,
) -> LLMUnderstanding:
    raw = (
        build_llm_understanding(
            message,
            profile,
            conversation_context=context,
            poi_knowledge=poi_knowledge,
        )
        or {}
    )
    raw = _merge_rule_understanding(raw, _rule_understanding(message))
    catalog = _catalog_from_knowledge(poi_knowledge or {})
    rule_tag_matches = PoiCatalogService().match_query_tags(message, catalog)
    legacy_intent = str(raw.get("intent_type") or detect_intent_type(message))
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
        for item in raw.get("target_categories") or detect_target_categories(message)
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
            adjustment_type=(
                _adjustment_type(message) if request_type == "plan_adjustment" else None
            ),
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
            "distance_preference": (
                "nearby" if any(x in message for x in ("附近", "别太远", "近一点")) else "normal"
            ),
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
        category = LEGACY_TO_LOGICAL.get(
            str(item.get("logical_category") or ""), str(item.get("logical_category") or "")
        )
        if category not in available:
            continue
        positive = [
            str(tag)
            for tag in item.get("positive_logic_tags", [])
            if str(tag) in available[category]
        ]
        negative = [
            str(tag)
            for tag in item.get("negative_logic_tags", [])
            if str(tag) in available[category]
        ]
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
        must_category = _infer_inspiration_must_category(must_keywords[0])
        return {
            "intent_type": "full_trip_plan",
            "target_categories": _inspiration_target_categories(must_category),
            "required_slots": _inspiration_required_slots(must_category),
            "must_pois": [
                {"name": keyword, "category": must_category, "must_include": True}
                for keyword in must_keywords
            ],
            "preference_keywords": [keyword for keyword in must_keywords if keyword],
            "scenario": "inspiration_must_poi",
        }

    if "我推荐附近适合今天去的本地生活地点" in message:
        return {
            "intent_type": "category_recommend",
            "target_categories": [
                "poi_activity",
                "poi_attraction",
                "poi_entertainment",
                "poi_shopping",
            ],
            "required_slots": ["activity", "attraction", "entertainment", "shopping"],
            "preference_keywords": ["今天", "附近", "热门"],
            "scenario": "nearby_today",
        }
    if "北京热门的吃喝玩乐地点" in message:
        return {
            "intent_type": "category_recommend",
            "target_categories": [
                "poi_restaurant",
                "poi_activity",
                "poi_attraction",
                "poi_entertainment",
                "poi_shopping",
            ],
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
            "target_categories": [
                "poi_activity",
                "poi_entertainment",
                "poi_shopping",
                "poi_beauty",
            ],
            "required_slots": ["activity_or_entertainment", "shopping"],
            "preference_keywords": ["室内", "轻松", "不晒"],
            "scenario": "indoor_light_route",
        }
    return {}


def _merge_rule_understanding(raw: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    if not rule:
        return raw
    merged = dict(raw)
    if rule.get("scenario") == "inspiration_must_poi":
        # 首页灵感卡片的“我想去 X”语义已经足够明确：
        # X 是必去点，槽位数量应保持可组合，避免 LLM 额外补槽导致路线组合被过滤到 0。
        for key in ("intent_type", "target_categories", "required_slots", "must_pois", "scenario"):
            merged[key] = rule[key]
        merged["preference_keywords"] = _dedupe([
            *list(rule.get("preference_keywords") or []),
            *list(raw.get("preference_keywords") or []),
        ])
        return merged
    for key, value in rule.items():
        if isinstance(value, list):
            if any(isinstance(item, dict) for item in value):
                merged[key] = _dedupe_dict_list([*value, *list(merged.get(key) or [])])
            else:
                merged[key] = _dedupe([*value, *list(merged.get(key) or [])])
        elif value not in (None, "", {}):
            merged[key] = value
    return merged


def _infer_inspiration_must_category(name: str) -> str:
    """根据首页灵感卡片中的 POI 名称，推断必去点最可能所在的 POI 表。"""

    text = str(name or "").lower()
    if any(
        token in text
        for token in ("skp", "专卖店", "商场", "购物", "品牌", "门店", "旗舰店", "piaget", "伯爵")
    ):
        return "poi_shopping"
    if any(
        token in text
        for token in (
            "开心麻花",
            "戏剧",
            "话剧",
            "音乐剧",
            "演出",
            "剧场",
            "沉浸",
            "聊斋",
            "展览",
            "活动",
        )
    ):
        return "poi_activity"
    if any(token in text for token in ("ktv", "影院", "电影", "密室", "桌游", "酒吧", "娱乐")):
        return "poi_entertainment"
    if any(token in text for token in ("美甲", "美容", "spa", "按摩", "护理")):
        return "poi_beauty"
    if any(token in text for token in ("健身", "瑜伽", "运动", "球馆")):
        return "poi_fitness"
    return "poi_attraction"


def _inspiration_target_categories(must_category: str) -> list[str]:
    category_order = {
        "poi_shopping": ["poi_shopping", "poi_activity", "poi_entertainment", "poi_attraction"],
        "poi_activity": ["poi_activity", "poi_entertainment", "poi_shopping", "poi_attraction"],
        "poi_entertainment": [
            "poi_entertainment",
            "poi_activity",
            "poi_shopping",
            "poi_attraction",
        ],
        "poi_beauty": ["poi_beauty", "poi_shopping", "poi_activity", "poi_entertainment"],
        "poi_fitness": ["poi_fitness", "poi_activity", "poi_shopping", "poi_entertainment"],
    }
    return category_order.get(
        must_category, ["poi_attraction", "poi_activity", "poi_entertainment", "poi_shopping"]
    )


def _inspiration_required_slots(must_category: str) -> list[str]:
    slot_order = {
        "poi_shopping": ["shopping", "activity_or_entertainment"],
        "poi_activity": ["activity_or_entertainment", "shopping"],
        "poi_entertainment": ["activity_or_entertainment", "shopping"],
        "poi_beauty": ["beauty", "shopping"],
        "poi_fitness": ["fitness", "activity_or_entertainment"],
    }
    return slot_order.get(must_category, ["attraction", "activity_or_entertainment"])


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
            text = text[len(prefix) :]
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
                address=" · ".join(part for part in (row_name, row_address) if part) or None,
                source="user_message",
            )
    return None


def _should_include_restaurant(message: str, raw: dict[str, Any]) -> bool:
    if any(keyword in message for keyword in MEAL_KEYWORDS):
        return True
    categories = [
        LEGACY_TO_LOGICAL.get(str(item), str(item)) for item in raw.get("target_categories", [])
    ]
    slots = [str(item) for item in raw.get("required_slots", [])]
    if "restaurant" in categories and any(
        keyword in message for keyword in ("找几个", "推荐", "餐厅", "吃")
    ):
        return True
    if any("restaurant" in slot or "餐" in slot for slot in slots) and any(
        keyword in message for keyword in MEAL_KEYWORDS
    ):
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
        start = _normalize_hour(
            float(range_match.group("start")), message[: range_match.start("start")]
        )
        end = _normalize_hour(
            float(range_match.group("end")),
            message[range_match.start("end") - 4 : range_match.start("end")],
        )
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
    match = re.search(
        r"(上午|中午|下午|晚上|今晚|今天)?\s*(\d{1,2})(?:[:：]\d{1,2})?\s*点", message
    )
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
        is_restaurant_slot = (
            slot_text in {"restaurant", "restaurant_2", "restaurant_or_cafe"} or "餐" in slot_text
        )
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
    from app.planning.state import POILogicalTagCatalog, POITableTagInfo

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

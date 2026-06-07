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

def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))

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

def _safe_float_value(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def _keyword_match(item: SafePOICandidate, keywords: list[str]) -> float:
    if not keywords:
        return 0.7
    text = " ".join(
        str(value or "")
        for value in [item.name, item.subcategory, item.address, " ".join(item.logic_tags)]
    ).lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in text) / len(keywords)

def _budget_score(price: float | None, soft_upper: float | None) -> float:
    if price is None or soft_upper is None:
        return 0.65
    return 1.0 if price <= soft_upper else max(0, 1 - (price - soft_upper) / max(1, soft_upper))

def _tag_overlap(tags: list[str], desired: list[str]) -> float:
    if not desired:
        return 0.7
    text = " ".join(tags)
    return sum(1 for tag in desired if tag in text) / len(desired)

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


__all__ = [name for name in globals() if name.startswith("_") or name.isupper()]

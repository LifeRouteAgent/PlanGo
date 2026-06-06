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

def score_candidates(
    raw: dict[str, list[SafePOICandidate]], constraints: FinalConstraints, memory_tags: list[str]
) -> dict[str, list[ScoredPOICandidate]]:
    # Graph 层保留旧函数名作为兼容入口，真实 POI 打分逻辑下沉到 scoring_service。
    return score_poi_candidates(raw, constraints, memory_tags)
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

def _balanced_keep_limit(slot_count: int) -> int:
    if slot_count <= 1:
        return 150
    if slot_count == 2:
        return 80
    return 100

def _price_band(price: float | None) -> str:
    if price is None or price <= 0:
        return "unknown"
    if price < 80:
        return "low"
    if price < 200:
        return "mid"
    return "high"


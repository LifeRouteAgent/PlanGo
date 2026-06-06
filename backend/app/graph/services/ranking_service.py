from __future__ import annotations

import re
from itertools import product
from math import asin, cos, radians, sin, sqrt
from datetime import datetime, timedelta
from typing import Any

from app.graph.intent_rules import detect_intent_type, detect_target_categories
from app.llm_agents.intent_understanding_agent import build_llm_understanding
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
)
from app.services.poi_repository import PoiRecallConstraints, PoiRepository
from app.services.poi_catalog_service import PoiCatalogService
from app.services.amap_route_service import AmapRouteService
from app.services.scoring_service import score_candidates as score_poi_candidates
from app.graph.payloads import normalize_response_payload

from app.graph.services.common import *

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


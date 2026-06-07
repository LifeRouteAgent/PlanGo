from __future__ import annotations

from app.planning.services.common import *
from app.planning.services.ranking_service import _candidate_index
from app.planning.state import CandidatePlan, ScoredPOICandidate, AvailabilityResults, POIAvailability, \
    FinalConstraints, LogicalRecallPlan


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
        item
        for item in availability.by_poi.values()
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
        max(
            relaxed.distance_policy.max_pair_distance_km * 1.35,
            relaxed.distance_policy.fallback_radius_km,
        ),
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
        max_total = policy_config.planning_rules.max_total_duration_minutes
        relaxed.hard_constraints.max_total_duration_minutes = min(
            max_total,
            int((relaxed.hard_constraints.max_total_duration_minutes or 240) * 1.15),
        )
        relaxed.time_policy.duration_minutes = relaxed.hard_constraints.max_total_duration_minutes
        relaxed.hard_constraints.max_route_minutes = int(
            (relaxed.hard_constraints.max_route_minutes or 90) * 1.25
        )
    return relaxed, relaxed_recall


def _mock_availability(item: ScoredPOICandidate) -> POIAvailability:
    raw_open = str(item.raw_extra.get("open_status") or "unknown").lower()
    open_status = "open_unknown" if raw_open in {"", "unknown", "none"} else raw_open
    if open_status not in {"open", "closed", "open_unknown"}:
        open_status = "open"
    seed = sum(ord(char) for char in item.poi_id + item.name)
    reservation_required = (
        item.logical_category in {"restaurant", "activity", "entertainment", "beauty"}
        or (item.rating or 0) >= 4.6
    )
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

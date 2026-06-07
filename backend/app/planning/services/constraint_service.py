from __future__ import annotations

from datetime import datetime, timedelta

from app.planning.policy_config import policy_config
from app.planning.services.common import *
from app.planning.services.intent_service import _normalize_restaurant_categories, _normalize_restaurant_slots, \
    _resolve_route_origin, _restaurant_allowed_for_understanding
from app.planning.state import (
    BudgetPolicy,
    DistancePolicy,
    FallbackLevel,
    FallbackPolicy,
    FinalConstraints,
    HardConstraints,
    KeywordRecallPlan,
    LLMUnderstanding,
    LogicalRecallPlan,
    RatingPolicy,
    SessionPreferenceProfile,
    SlotRecallRequirement,
    SoftPreferences,
    TimePolicy, SlotDetail,
)


def build_constraints(
    understanding: LLMUnderstanding,
    *,
    city: str | None,
    origin: Any,
    previous: dict[str, Any] | None = None,
    session_preference: SessionPreferenceProfile | None = None,
) -> tuple[FinalConstraints, LogicalRecallPlan]:
    previous = previous or {}
    rules = policy_config.planning_rules
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
    slot_details = [slot for slot in understanding.slots.slot_details if slot.required]
    if not slot_details and understanding.slots.required_slots:
        slot_details = [
            SlotDetail(
                slot_id=slot,
                slot_name=slot,
                required=True,
                candidate_logical_categories=[],
            )
            for slot in understanding.slots.required_slots
        ]
    slot_duration_minutes = _slot_duration_minutes(slot_details, rules)
    explicit_duration_minutes = (
        round(understanding.time.duration_hours * 60)
        if understanding.time.duration_hours
        else None
    )
    duration_minutes = _total_duration_minutes(
        slot_duration_minutes,
        explicit_duration_minutes,
        rules,
    )
    if explicit_duration_minutes:
        slot_duration_minutes = _fit_slot_durations_to_total(
            slot_duration_minutes,
            duration_minutes,
            rules,
        )
    start_time = understanding.time.start_time or datetime.now().replace(
        hour=rules.default_start_hour, minute=0, second=0, microsecond=0
    )
    restaurant_allowed = _restaurant_allowed_for_understanding(understanding)
    required_slots = (
        understanding.slots.required_slots or SCENE_SLOTS.get(scene, SCENE_SLOTS["unknown"])[0]
    )
    required_slots = [slot.slot_id for slot in slot_details] or understanding.slots.required_slots
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
                for slot in slot_details
                for category in slot.candidate_logical_categories
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
    preferences = _dedupe([
        *previous.get("preference_keywords", []),
        *understanding.poi_keyword_intent.preference_poi_keywords,
    ])
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
            slot_duration_minutes=slot_duration_minutes,
            slot_logical_categories={
                slot.slot_id: list(slot.candidate_logical_categories)
                for slot in slot_details
                if slot.slot_id
            },
            slot_names={slot.slot_id: slot.slot_name for slot in slot_details if slot.slot_id},
            max_total_duration_minutes=duration_minutes,
            max_route_minutes=rules.max_route_minutes,
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
    slot_detail_by_id = {slot.slot_id: slot for slot in slot_details}
    for slot in required_slots:
        detail = slot_detail_by_id.get(slot)
        detail_categories = list(detail.candidate_logical_categories) if detail else []
        logical_categories = (
            [category for category in detail_categories if category in preferred_categories]
            or detail_categories
            or preferred_categories
        )
        logical_categories = _normalize_restaurant_categories(
            logical_categories,
            restaurant_allowed,
            understanding.intent.request_type,
        )
        if "restaurant" in logical_categories:
            restaurant_query_count += 1
            if restaurant_query_count > 2:
                logical_categories = [
                    category for category in logical_categories if category != "restaurant"
                ]
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


def _slot_duration_minutes(slot_details: list[SlotDetail], rules: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for slot in slot_details:
        raw_duration = slot.expected_duration_minutes or rules.fallback_slot_duration_minutes
        result[slot.slot_id] = _clamp_minutes(
            raw_duration,
            rules.min_slot_duration_minutes,
            rules.max_slot_duration_minutes,
        )
    return result


def _total_duration_minutes(
    slot_duration_minutes: dict[str, int],
    explicit_duration_minutes: int | None,
    rules: Any,
) -> int:
    if explicit_duration_minutes:
        return _clamp_minutes(
            explicit_duration_minutes,
            rules.min_total_duration_minutes,
            rules.max_total_duration_minutes,
        )
    visit_minutes = sum(slot_duration_minutes.values())
    route_buffer = max(0, len(slot_duration_minutes) - 1) * 20
    if visit_minutes <= 0:
        visit_minutes = rules.fallback_slot_duration_minutes
    return _clamp_minutes(
        visit_minutes + route_buffer,
        rules.min_total_duration_minutes,
        rules.max_total_duration_minutes,
    )


def _fit_slot_durations_to_total(
    slot_duration_minutes: dict[str, int],
    total_duration_minutes: int,
    rules: Any,
) -> dict[str, int]:
    if not slot_duration_minutes:
        return {}
    route_buffer = max(0, len(slot_duration_minutes) - 1) * 20
    available_visit_minutes = max(
        rules.min_slot_duration_minutes * len(slot_duration_minutes),
        total_duration_minutes - route_buffer,
    )
    current_visit_minutes = sum(slot_duration_minutes.values())
    if current_visit_minutes <= available_visit_minutes:
        return slot_duration_minutes
    ratio = available_visit_minutes / max(1, current_visit_minutes)
    fitted = {
        slot: _clamp_minutes(
            round(duration * ratio),
            rules.min_slot_duration_minutes,
            rules.max_slot_duration_minutes,
        )
        for slot, duration in slot_duration_minutes.items()
    }
    overflow = sum(fitted.values()) - available_visit_minutes
    if overflow <= 0:
        return fitted
    for slot in sorted(fitted, key=fitted.get, reverse=True):
        reducible = max(0, fitted[slot] - rules.min_slot_duration_minutes)
        reduction = min(reducible, overflow)
        fitted[slot] -= reduction
        overflow -= reduction
        if overflow <= 0:
            break
    return fitted


def _clamp_minutes(value: int | float, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(round(value))))


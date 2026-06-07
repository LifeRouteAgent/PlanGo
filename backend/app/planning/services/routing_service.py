from __future__ import annotations

from app.planning.services.common import *


def create_route_plans(
    balanced: dict[str, list[ScoredPOICandidate]], constraints: FinalConstraints
) -> list[CandidatePlan]:
    slots = [slot for slot in constraints.hard_constraints.required_slots if balanced.get(slot)]
    if not slots:
        slots = [slot for slot, items in balanced.items() if items]
    if not slots:
        return []
    groups = [balanced[slot][: _route_combo_limit(len(slots))] for slot in slots]
    if any(not group for group in groups):
        return []
    must_ids = {item.poi_id for group in balanced.values() for item in group if item.must_include}

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


def _route_combo_limit(slot_count: int) -> int:
    if slot_count <= 2:
        return 40
    if slot_count == 3:
        return 30
    return 20


def _has_duplicate_place(items: list[ScoredPOICandidate]) -> bool:
    seen: set[str] = set()
    for item in items:
        key = "|".join(
            [item.poi_id, (item.name or "").strip().lower(), (item.address or "").strip().lower()]
        )
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


def _has_too_close_adjacent_pois(
    items: list[ScoredPOICandidate], min_distance_km: float = 1.0
) -> bool:
    for previous, current in zip(items, items[1:], strict=False):
        if (
            previous.lat is None
            or previous.lng is None
            or current.lat is None
            or current.lng is None
        ):
            continue
        distance = _haversine_km((previous.lat, previous.lng), (current.lat, current.lng))
        if distance < min_distance_km:
            return True
    return False


def _semantic_keys(item: ScoredPOICandidate) -> set[str]:
    generic = {
        "restaurant",
        "entertainment",
        "activity",
        "shopping",
        "fitness",
        "beauty",
        "餐饮服务",
        "餐饮相关",
        "餐厅美食",
        "体育休闲服务",
        "娱乐场所",
        "运动场馆",
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
    visit_minutes = [
        _duration_for_slot(slot, item, constraints)
        for slot, item in zip(slots, items, strict=False)
    ]
    estimated_budget = sum(float(item.avg_price or 0) for item in items)
    start = constraints.time_policy.start_time or datetime.now().replace(
        hour=14, minute=0, second=0, microsecond=0
    )
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
                description=constraints.hard_constraints.slot_names.get(slot)
                or item.subcategory
                or item.logical_category,
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
        points.append(
            (constraints.hard_constraints.origin.lat, constraints.hard_constraints.origin.lng)
        )
    points.extend(
        (item.lat, item.lng) for item in items if item.lat is not None and item.lng is not None
    )
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


def _duration_for_slot(
    slot: str,
    item: ScoredPOICandidate,
    constraints: FinalConstraints,
) -> int:
    duration = constraints.hard_constraints.slot_duration_minutes.get(slot)
    if duration:
        return duration
    return constraints.time_policy.duration_minutes or 90


def _budget_fit_label(estimated: float, constraints: FinalConstraints) -> str:
    total = constraints.budget_policy.total_budget
    if not total:
        return "unknown"
    if estimated <= total:
        return "good"
    if estimated <= total * 1.3:
        return "slightly_over"
    return "over"


def _route_segments_for_items(
    items: list[dict[str, Any]], origin: OriginPoint | None = None
) -> list[dict[str, Any]]:
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
        segments.append(
            _route_segment_between(start, end, route_service, from_type="poi", to_type="poi")
        )
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
    if (
        start_lat is not None
        and start_lng is not None
        and end_lat is not None
        and end_lng is not None
    ):
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

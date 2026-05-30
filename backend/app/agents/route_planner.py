from __future__ import annotations

import math
import os
from itertools import product
from datetime import datetime, timedelta
from typing import Any

from app.agents.issue_utils import make_issue
from app.services.amap_route_service import AmapRouteService
from app.state.plan_state import PlanState, PlanStatePatch

EARTH_RADIUS_KM = 6371.0088


def route_time_planner_node(state: PlanState) -> PlanStatePatch:
    """路线与时间线规划节点。

    Gate 4 开始，本节点不再使用固定 mock 路线耗时，而是：
    1. 根据 Planner 输出的 required_slots 选择适合槽位的 POI。
    2. 用 Haversine 公式估算相邻 POI 的直线距离。
    3. 根据距离选择步行、打车、地铁/打车组合等本地交通方式。
    4. 生成 2-3 个候选时间线方案，交给 Verifier 校验。

    当前仍不调用高德路线 API。后续接高德时，只需要替换
    `_estimate_transport_segment()` 的实现，把估算距离和耗时换成真实路线结果。
    """

    recommended = state.get("recommended_pois", {})
    all_candidates = [item for items in recommended.values() for item in items]
    if not all_candidates:
        return {
            "errors": [make_issue("candidate_empty", source="route_time_planner")],
            "logs": ["Route & Time Planner: no recommended POIs available"],
        }

    dag_plan = state.get("dag_plan", {})
    constraints = state.get("constraints", {})
    duration_limit = int(float(constraints.get("duration_hours", 10))) * 60
    max_route_minutes = int(constraints.get("max_route_minutes", 90))
    duration_is_hard = bool(constraints.get("duration_is_hard"))
    route_limit_is_hard = bool(constraints.get("route_limit_is_hard"))
    start_time = str(constraints.get("start_time", "10:00"))
    origin_item = _origin_from_user_profile(state.get("user_profile", {}))

    candidate_item_sets = _build_candidate_item_sets(
        all_candidates,
        dag_plan,
        user_query=state.get("user_query", ""),
        constraints=constraints,
    )
    candidate_plans: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    route_service = None if os.environ.get("PYTEST_CURRENT_TEST") else AmapRouteService()

    for index, items in enumerate(candidate_item_sets, start=1):
        route_segments = _build_route_segments(items, route_service, origin_item=origin_item)
        route_minutes = sum(segment["duration_minutes"] for segment in route_segments)
        if state.get("force_route_timeout") and state.get("replanning_count", 0) <= 1:
            route_minutes = max_route_minutes + 20
            route_segments = [
                {
                    **segment,
                    "duration_minutes": max_route_minutes + 20,
                    "forced_timeout": True,
                }
                for segment in route_segments
            ] or [{
                "from": "",
                "to": "",
                "distance_km": 0,
                "transport_mode": "forced_timeout",
                "duration_minutes": max_route_minutes + 20,
                "forced_timeout": True,
            }]

        stay_minutes = _fit_stay_minutes(items, route_minutes, duration_limit)
        total_duration = _total_duration_for_state(
            state, stay_minutes, route_minutes, duration_limit
        )
        timeline = _build_timeline(items, route_segments, start_time, stay_minutes)
        estimated_budget = _estimate_budget(items)
        plan = {
            "id": f"plan_route_{index}",
            "plan_id": f"plan_route_{index}",
            # 保持历史主方案 id，避免旧接口和测试依赖突然断裂。
            "legacy_id": "plan_mock_1" if index == 1 else "",
            "title": _title_for_template(dag_plan.get("planning_template", "meal_plus_activity")),
            "planning_template": dag_plan.get("planning_template", "meal_plus_activity"),
            "required_slots": dag_plan.get("required_slots", []),
            "movement_policy": dag_plan.get("movement_policy", "balanced_local"),
            "candidate_strategy": dag_plan.get("candidate_strategy", "slot_balance"),
            "items": items,
            "timeline": timeline,
            "route_segments": route_segments,
            "total_distance_km": round(
                sum(segment["distance_km"] for segment in route_segments), 2
            ),
            "total_duration_minutes": total_duration,
            "route_minutes": route_minutes,
            "estimated_budget": estimated_budget,
            "fit_summary": _fit_summary(
                items=items,
                route_minutes=route_minutes,
                total_duration=total_duration,
                duration_limit=duration_limit,
                estimated_budget=estimated_budget,
                budget=int(float(constraints.get("budget", 600))),
            ),
        }
        # 暂时把第一个方案 id 兼容为 plan_mock_1；后续前端完全切到 route id 后再移除。
        if index == 1:
            plan["id"] = "plan_mock_1"
            plan["plan_id"] = "plan_mock_1"
        candidate_plans.append(plan)
        routes.append({
            "mode": _route_mode(route_segments),
            "movement_policy": dag_plan.get("movement_policy", "balanced_local"),
            "total_distance_km": plan["total_distance_km"],
            "total_minutes": route_minutes,
            "segments": route_segments,
        })

    candidate_plans, routes = _prefer_feasible_plans(
        candidate_plans,
        routes,
        max_route_minutes,
        duration_limit,
        route_limit_is_hard=route_limit_is_hard,
        duration_is_hard=duration_is_hard,
        force_keep_all=bool(
            state.get("force_route_timeout") and state.get("replanning_count", 0) <= 1
        )
        or bool(state.get("force_duration_exceeded") and state.get("replanning_count", 0) <= 1),
    )

    return {
        "candidate_plans": candidate_plans,
        "routes": routes,
        "logs": [
            f"Route & Time Planner: generated {len(candidate_plans)} route timelines",
            *_route_harness_logs(route_service),
        ],
    }


def _build_candidate_item_sets(
    candidates: list[dict[str, Any]],
    dag_plan: dict[str, Any],
    *,
    user_query: str = "",
    constraints: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    """生成多个候选 POI 组合。

    当前生成三类候选：
    - slot_based：严格按 Planner 槽位挑选。
    - compact：以最高分候选为锚点，选择距离最近的其他候选。
    - score_based：按推荐分排序，并确保餐厅进入完整方案。
    """

    sorted_candidates = sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)
    required_slots = list(dag_plan.get("slot_sequence") or dag_plan.get("required_slots") or [])
    desired_count = _desired_item_count(required_slots)

    slot_search_sets = _build_slot_combination_sets(
        sorted_candidates,
        required_slots,
        user_query=user_query,
        constraints=constraints or {},
    )
    variants: list[list[dict[str, Any]]] = list(slot_search_sets)
    slot_based = _select_slot_based(sorted_candidates, required_slots, desired_count)
    if slot_based:
        variants.append(slot_based)

    compact = _select_compact(sorted_candidates, desired_count)
    if compact:
        variants.append(compact)

    score_based = _ensure_restaurant(sorted_candidates[:desired_count], sorted_candidates)
    if score_based:
        variants.append(score_based)

    offset_score_based = _select_offset_score_based(sorted_candidates, desired_count)
    if offset_score_based:
        variants.append(offset_score_based)

    must_items = [item for item in sorted_candidates if item.get("must_include")]
    if must_items:
        variants = [_ensure_must_items(variant, must_items, desired_count) for variant in variants]

    ranked_variants = sorted(
        _dedupe_item_sets(variants),
        key=lambda items: _combination_rank_key(items, required_slots),
    )
    preferred_variants = _filter_variants_by_explicit_preference(
        ranked_variants,
        user_query,
        constraints=constraints or {},
    )
    if preferred_variants:
        ranked_variants = preferred_variants
    return _select_diverse_item_sets(ranked_variants, limit=3)


def _build_slot_combination_sets(
    candidates: list[dict[str, Any]],
    required_slots: list[str],
    *,
    user_query: str = "",
    constraints: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    """把每个规划槽位映射为候选池，并枚举最多 12 个高质量组合。

    本地生活规划的排序单位是“方案组合”而不是单个 POI。这里先为每个 slot 取 Top N，
    再对组合按总分、移动距离、重复类别排序，确保比如“麻将 -> KTV”不会混进餐厅或健身。
    """

    if not required_slots:
        return []

    slot_pools: list[list[dict[str, Any] | None]] = []
    for slot in required_slots:
        pool = _top_candidates_for_slot(
            candidates,
            slot,
            top_n=12,
            user_query=user_query,
            constraints=constraints or {},
        )
        if slot.startswith("optional"):
            slot_pools.append([None, *pool[:6]])
        elif pool:
            slot_pools.append(pool)
        else:
            return []

    raw_combinations: list[list[dict[str, Any]]] = []
    for combo in product(*slot_pools):
        items = [item for item in combo if item is not None]
        if not items or _has_duplicate_items(items):
            continue
        raw_combinations.append(items)

    ranked = sorted(
        _dedupe_item_sets(raw_combinations),
        key=lambda items: _combination_rank_key(items, required_slots),
    )
    return ranked[:12]


def _top_candidates_for_slot(
    candidates: list[dict[str, Any]],
    slot: str,
    *,
    top_n: int,
    user_query: str = "",
    constraints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """为某个 slot 取 Top N 候选，先按槽位适配，再按推荐分排序。"""

    matched = [
        item for item in candidates if _category_matches_slot(str(item.get("category", "")), slot)
    ]
    preferred = _filter_by_slot_preference(
        matched,
        slot,
        user_query,
        constraints=constraints or {},
    )
    if preferred:
        matched = preferred
    return sorted(
        matched,
        key=lambda item: (
            -float(item.get("score", 0) or 0),
            -float(item.get("scene_fit", 0.7) or 0.7),
            str(item.get("id", "")),
        ),
    )[:top_n]


def _filter_by_slot_preference(
    candidates: list[dict[str, Any]],
    slot: str,
    user_query: str,
    *,
    constraints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """按结构化垂类偏好收窄 slot 候选。

    LLM 会把“唱歌”解析成 ktv 这类 semantic_type；规则关键词只在 LLM 不可用时兜底。
    """

    semantic_keywords = _semantic_keywords_from_constraints(constraints or {})
    if semantic_keywords and "entertainment" in slot:
        filtered = [item for item in candidates if _poi_matches_keywords(item, tuple(semantic_keywords))]
        if filtered:
            return filtered

    keyword_groups: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("唱歌", "KTV", "ktv", "K歌", "k歌"), ("ktv", "KTV", "唱歌", "K歌", "量贩", "歌厅")),
        (("麻将", "打牌", "棋牌"), ("麻将", "棋牌", "桌游", "牌")),
        (("电影", "影院", "看电影"), ("电影", "影院", "影城")),
        (("密室",), ("密室",)),
        (("剧本杀",), ("剧本杀",)),
    ]
    if "entertainment" not in slot:
        return []
    for query_keywords, poi_keywords in keyword_groups:
        if not any(keyword in user_query for keyword in query_keywords):
            continue
        filtered = [item for item in candidates if _poi_matches_keywords(item, poi_keywords)]
        if len(filtered) >= 2:
            return filtered
    return []


def _poi_matches_keywords(item: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    """判断 POI 名称、子类、标签或推荐理由是否命中关键词。"""

    fields = [
        str(item.get("name", "")),
        str(item.get("subcategory", "")),
        str(item.get("reason", "")),
        str(item.get("recommendation_reason", "")),
        " ".join(str(tag) for tag in item.get("tags", []) if tag),
    ]
    text = " ".join(fields)
    return any(keyword in text for keyword in keywords)


def _filter_variants_by_explicit_preference(
    variants: list[list[dict[str, Any]]],
    user_query: str,
    *,
    constraints: dict[str, Any] | None = None,
) -> list[list[dict[str, Any]]]:
    """当用户明确给出娱乐垂类时，过滤掉语义不匹配的备选组合。

    例如“唱歌”不能用电影城凑数；“打麻将”不能用普通影院凑数。
    如果过滤后没有候选，则保留原结果，避免候选池过窄导致完全无方案。
    """

    semantic_keywords = _semantic_keywords_from_constraints(constraints or {})
    preference_keywords: tuple[str, ...] = tuple(semantic_keywords)
    if not preference_keywords and any(keyword in user_query for keyword in ("唱歌", "KTV", "ktv", "K歌", "k歌")):
        preference_keywords = ("ktv", "KTV", "唱歌", "K歌", "量贩", "歌厅")
    elif any(keyword in user_query for keyword in ("麻将", "打牌", "棋牌")):
        preference_keywords = ("麻将", "棋牌", "桌游", "牌")
    elif any(keyword in user_query for keyword in ("电影", "影院", "看电影")):
        preference_keywords = ("电影", "影院", "影城")
    if not preference_keywords:
        return []

    filtered: list[list[dict[str, Any]]] = []
    for variant in variants:
        entertainment_items = [
            item for item in variant if item.get("category") == "poi_entertainment"
        ]
        if entertainment_items and all(
            _poi_matches_keywords(item, preference_keywords) for item in entertainment_items
        ):
            filtered.append(variant)
    return filtered


def _semantic_keywords_from_constraints(constraints: dict[str, Any]) -> list[str]:
    """优先使用 LLM 抽出的活动语义关键词，规则只在上层兜底。"""

    keywords: list[str] = []
    for intent in constraints.get("activity_intents", []) or []:
        if not isinstance(intent, dict):
            continue
        if not intent.get("must_match"):
            continue
        semantic_type = str(intent.get("semantic_type") or "").lower()
        if semantic_type == "ktv":
            keywords.extend(["ktv", "KTV", "唱歌", "K歌", "量贩", "歌厅"])
        elif semantic_type in {"chess_cards", "mahjong", "cards"}:
            keywords.extend(["麻将", "棋牌", "桌游", "牌"])
        elif semantic_type == "cinema":
            keywords.extend(["电影", "影院", "影城"])
        keywords.extend(str(item) for item in intent.get("keywords", []) or [])
    return list(dict.fromkeys(keyword for keyword in keywords if keyword))


def _has_duplicate_items(items: list[dict[str, Any]]) -> bool:
    """同一个 POI 不能在一个方案中重复出现。"""

    ids = [str(item.get("id")) for item in items]
    return len(ids) != len(set(ids))


def _ensure_must_items(
    items: list[dict[str, Any]],
    must_items: list[dict[str, Any]],
    desired_count: int,
) -> list[dict[str, Any]]:
    """确保用户明确点名的 POI 进入每个候选方案。

    must POI 的优先级高于普通高分候选；如果槽位已满，会优先替换同类普通 POI，
    再替换最低分普通 POI，避免“环球影城”被影院/KTV高分候选挤掉。
    """

    result = list(items)
    for must in must_items:
        must_id = str(must.get("id"))
        if any(str(item.get("id")) == must_id for item in result):
            continue
        same_category_index = next(
            (
                index
                for index, item in enumerate(result)
                if item.get("category") == must.get("category") and not item.get("must_include")
            ),
            None,
        )
        if same_category_index is not None:
            result[same_category_index] = must
            continue
        if len(result) < max(desired_count, len(must_items)):
            result.insert(0, must)
            continue
        replaceable_indexes = [
            index for index, item in enumerate(result) if not item.get("must_include")
        ]
        if replaceable_indexes:
            worst_index = min(
                replaceable_indexes,
                key=lambda index: float(result[index].get("score", 0) or 0),
            )
            result[worst_index] = must
    return result


def _combination_rank_key(
    items: list[dict[str, Any]],
    required_slots: list[str],
) -> tuple[float, float, int, tuple[str, ...]]:
    """组合排序：优先偏好和动线，再考虑类别重复和稳定性。"""

    total_score = sum(float(item.get("score", 0) or 0) for item in items)
    total_distance = _total_haversine_distance(items)
    duplicate_categories = _duplicate_category_count(items, required_slots)
    return (
        -total_score + total_distance * 2.0 + duplicate_categories * 2,
        total_distance,
        duplicate_categories,
        tuple(str(item.get("id")) for item in items),
    )


def _total_haversine_distance(items: list[dict[str, Any]]) -> float:
    """估算一个组合按当前顺序移动的直线总距离。"""

    return sum(
        _haversine_km(previous["lat"], previous["lon"], current["lat"], current["lon"])
        for previous, current in zip(items, items[1:])
    )


def _duplicate_category_count(items: list[dict[str, Any]], required_slots: list[str]) -> int:
    """统计不必要的同类重复；同一类被多个 slot 明确需要时不惩罚。"""

    categories = [str(item.get("category", "")) for item in items]
    allowed_repeats = max(0, len(required_slots) - len(set(required_slots)))
    return max(0, len(categories) - len(set(categories)) - allowed_repeats)


def _desired_item_count(required_slots: list[str]) -> int:
    """根据槽位数量决定本次时间线放几个 POI。"""

    if not required_slots:
        return 3
    required = [slot for slot in required_slots if not slot.startswith("optional")]
    return max(1, min(3, len(required) + 1 if len(required) == 1 else len(required)))


def _select_slot_based(
    candidates: list[dict[str, Any]],
    required_slots: list[str],
    desired_count: int,
) -> list[dict[str, Any]]:
    """按 Planner 槽位选择 POI，避免路线规划盲目取前几个高分候选。"""

    selected: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    optimized_pair = _select_optimized_first_pair(candidates, required_slots)
    if optimized_pair:
        for item in optimized_pair:
            selected.append(item)
            used_ids.add(str(item["id"]))

    for slot in required_slots:
        if any(_category_matches_slot(str(item.get("category", "")), slot) for item in selected):
            continue
        if slot.startswith("optional") and len(selected) >= desired_count:
            continue
        matched = _first_matching_slot(
            candidates, slot, used_ids, selected[-1] if selected else None
        )
        if matched:
            selected.append(matched)
            used_ids.add(str(matched["id"]))
        if len(selected) >= desired_count:
            break

    if len(selected) < desired_count:
        for item in candidates:
            if str(item["id"]) not in used_ids:
                selected.append(item)
                used_ids.add(str(item["id"]))
            if len(selected) >= desired_count:
                break
    return _ensure_restaurant(selected, candidates)


def _select_optimized_first_pair(
    candidates: list[dict[str, Any]],
    required_slots: list[str],
) -> list[dict[str, Any]]:
    """为前两个核心槽位选择距离更合理的一对 POI。

    本地生活规划里最常见的是“活动/娱乐 + 餐厅”。如果先按单点分数选娱乐，
    再找餐厅，容易出现跨区移动。这里对前两个非 optional 槽位做成对搜索。
    """

    core_slots = [slot for slot in required_slots if not slot.startswith("optional")][:2]
    if len(core_slots) < 2:
        return []

    first_candidates = [
        item
        for item in candidates
        if _category_matches_slot(str(item.get("category", "")), core_slots[0])
    ]
    second_candidates = [
        item
        for item in candidates
        if _category_matches_slot(str(item.get("category", "")), core_slots[1])
    ]
    pairs: list[tuple[float, float, dict[str, Any], dict[str, Any]]] = []
    for first in first_candidates:
        for second in second_candidates:
            if first["id"] == second["id"]:
                continue
            distance = _haversine_km(first["lat"], first["lon"], second["lat"], second["lon"])
            score = float(first.get("score", 0)) + float(second.get("score", 0))
            pairs.append((distance, -score, first, second))
    if not pairs:
        return []
    _, _, first, second = min(pairs, key=lambda item: (item[0], item[1]))
    return [first, second]


def _first_matching_slot(
    candidates: list[dict[str, Any]],
    slot: str,
    used_ids: set[str],
    previous_item: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """找到第一个适配槽位且未使用的候选。

    如果已有上一个槽位，则优先选择距离上一个 POI 更近的候选，而不是盲目选择最高分。
    这能避免“城区电影 + 远郊餐厅”这种本地生活不可执行组合。
    """

    matched_candidates: list[dict[str, Any]] = []
    for item in candidates:
        if str(item["id"]) in used_ids:
            continue
        if _category_matches_slot(str(item.get("category", "")), slot):
            matched_candidates.append(item)
    if not matched_candidates:
        return None
    if previous_item:
        return min(
            matched_candidates,
            key=lambda item: (
                _haversine_km(previous_item["lat"], previous_item["lon"], item["lat"], item["lon"]),
                -item.get("score", 0),
            ),
        )
    return matched_candidates[0]


def _category_matches_slot(category: str, slot: str) -> bool:
    """判断统一 POI 类别是否能填充某个规划槽位。"""

    slot_map = {
        "restaurant": {"poi_restaurant"},
        "restaurant_or_tea": {"poi_restaurant", "poi_beauty"},
        "attraction": {"poi_attraction"},
        "activity": {"poi_activity", "poi_attraction"},
        "family_activity": {"poi_activity", "poi_attraction", "poi_shopping"},
        "activity_or_entertainment": {"poi_activity", "poi_entertainment", "poi_attraction"},
        "entertainment": {"poi_entertainment"},
        "optional_lifestyle": {"poi_entertainment", "poi_fitness", "poi_beauty", "poi_shopping"},
        "lifestyle": {"poi_entertainment", "poi_fitness", "poi_beauty"},
        "shopping": {"poi_shopping"},
        "optional_shopping": {"poi_shopping"},
        "optional_entertainment": {"poi_entertainment"},
        "cafe_or_walk": {"poi_restaurant", "poi_attraction", "poi_shopping"},
    }
    return category in slot_map.get(slot, {category})


def _select_compact(candidates: list[dict[str, Any]], desired_count: int) -> list[dict[str, Any]]:
    """以最高分 POI 为锚点，选择距离最近的候选，生成低移动成本方案。"""

    if not candidates:
        return []
    anchor = candidates[0]
    rest = sorted(
        candidates[1:],
        key=lambda item: (
            _haversine_km(anchor["lat"], anchor["lon"], item["lat"], item["lon"]),
            -item.get("score", 0),
        ),
    )
    return _ensure_restaurant([anchor, *rest[: max(0, desired_count - 1)]], candidates)


def _select_offset_score_based(
    candidates: list[dict[str, Any]], desired_count: int
) -> list[dict[str, Any]]:
    """生成第三个错位高分备选方案。

    前三个策略在候选较集中时容易得到相同组合。这个策略会跳过最高分锚点，
    从第 2-4 个高分候选里选择不同起点，再补一个附近餐厅，尽量给用户真正不同的第三方案。
    """

    if len(candidates) <= desired_count:
        return []
    start = min(1, len(candidates) - 1)
    selected = candidates[start : start + desired_count]
    if len(selected) < desired_count:
        selected = [*selected, *candidates[: desired_count - len(selected)]]
    return _ensure_restaurant(selected, candidates)


def _ensure_restaurant(
    selected: list[dict[str, Any]],
    all_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """完整本地生活方案优先确保餐厅进入时间线。

    如果已有活动/娱乐锚点，不选最高分餐厅，而选离锚点最近的餐厅。
    本地生活规划里，“能走得顺”通常比单点分数更重要。
    """

    if any(item.get("category") == "poi_restaurant" for item in selected):
        return selected
    restaurants = [item for item in all_candidates if item.get("category") == "poi_restaurant"]
    if not restaurants:
        return selected
    anchor = selected[0] if selected else None
    restaurant = (
        min(
            restaurants,
            key=lambda item: (
                _haversine_km(anchor["lat"], anchor["lon"], item["lat"], item["lon"]),
                -item.get("score", 0),
            ),
        )
        if anchor
        else restaurants[0]
    )
    if len(selected) >= 3:
        return [*selected[:-1], restaurant]
    return [*selected, restaurant]


def _dedupe_item_sets(variants: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """去重候选组合，避免多个策略生成完全相同的方案。"""

    seen: set[tuple[str, ...]] = set()
    result: list[list[dict[str, Any]]] = []
    for variant in variants:
        key = tuple(str(item["id"]) for item in variant)
        if key and key not in seen:
            seen.add(key)
            result.append(variant)
    return result


def _select_diverse_item_sets(
    ranked_variants: list[list[dict[str, Any]]],
    *,
    limit: int,
) -> list[list[dict[str, Any]]]:
    """从已排序组合中挑选地点差异更明显的方案。

    “更多备选方案”的价值应该是给用户不同地点组合，而不是同一批 POI 换一个时间线。
    因此这里会优先保留非 must POI 差异足够大的组合；用户点名的 must POI
    允许在所有方案中重复，例如“环球影城”必须一直保留。
    """

    selected: list[list[dict[str, Any]]] = []
    for variant in ranked_variants:
        if not variant:
            continue
        if not selected:
            selected.append(variant)
            continue
        if all(_non_must_jaccard_distance(variant, existing) >= 0.45 for existing in selected):
            selected.append(variant)
        if len(selected) >= limit:
            return selected

    # 候选池不足时再放宽阈值，但仍避免完全相同的 POI 组合。
    for variant in ranked_variants:
        if len(selected) >= limit:
            break
        key = _item_set_key(variant)
        if key and all(_item_set_key(existing) != key for existing in selected):
            selected.append(variant)
    return selected[:limit]


def _item_set_key(items: list[dict[str, Any]]) -> tuple[str, ...]:
    """用 POI ID 集合判断两个方案是否完全相同，忽略时间顺序差异。"""

    return tuple(sorted(str(item.get("id")) for item in items if item.get("id")))


def _non_must_jaccard_distance(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> float:
    """计算两个组合在非 must POI 上的差异度。"""

    left_ids = {
        str(item.get("id")) for item in left if item.get("id") and not item.get("must_include")
    }
    right_ids = {
        str(item.get("id")) for item in right if item.get("id") and not item.get("must_include")
    }
    if not left_ids and not right_ids:
        return 0.0
    union = left_ids | right_ids
    if not union:
        return 0.0
    return 1 - len(left_ids & right_ids) / len(union)


def _prefer_feasible_plans(
    plans: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    max_route_minutes: int,
    duration_limit: int,
    *,
    route_limit_is_hard: bool,
    duration_is_hard: bool,
    force_keep_all: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """优先返回路线和总时长可行的候选。

    Verifier 仍然是最终校验者，但 Route Planner 不应该把明显不可行的候选全部交上去。
    否则只要某个候选超时，当前 Verifier 就会触发回退，掩盖其他可行方案。
    """

    if force_keep_all:
        return plans, routes
    if not route_limit_is_hard and not duration_is_hard:
        return plans, routes

    feasible_pairs = [
        (plan, route)
        for plan, route in zip(plans, routes)
        if (not route_limit_is_hard or plan.get("route_minutes", 0) <= max_route_minutes)
        and (not duration_is_hard or plan.get("total_duration_minutes", 0) <= duration_limit)
    ]
    if not feasible_pairs:
        return plans[:1], routes[:1]
    filtered_plans, filtered_routes = zip(*feasible_pairs)
    return list(filtered_plans), list(filtered_routes)


def _build_route_segments(
    items: list[dict[str, Any]],
    route_service: AmapRouteService | None = None,
    *,
    origin_item: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """根据相邻 POI 生成路线段。"""

    segments: list[dict[str, Any]] = []
    if origin_item and items:
        segments.append(_estimate_transport_segment(origin_item, items[0], route_service))
    for previous, current in zip(items, items[1:]):
        segments.append(_estimate_transport_segment(previous, current, route_service))
    return segments


def _estimate_transport_segment(
    previous: dict[str, Any],
    current: dict[str, Any],
    route_service: AmapRouteService | None = None,
) -> dict[str, Any]:
    """估算两个 POI 之间的本地交通方式和耗时。

    规则来自当前阶段的工程假设：
    - 0-1km：步行 10-15 分钟。
    - 1-5km：打车/自驾 10-25 分钟。
    - 5-15km：地铁/打车 25-50 分钟。
    - 15km+：跨区移动，除非用户明确接受，否则后续 Verifier/Ranker 会降权。
    """

    haversine_distance_km = _haversine_km(
        previous["lat"], previous["lon"], current["lat"], current["lon"]
    )
    if haversine_distance_km <= 1:
        mode = "walk"
        duration = max(8, math.ceil(haversine_distance_km / 4.5 * 60) + 3)
    elif haversine_distance_km <= 5:
        mode = "taxi"
        duration = max(10, math.ceil(haversine_distance_km / 25 * 60) + 8)
    elif haversine_distance_km <= 15:
        mode = "transit_or_taxi"
        duration = max(25, math.ceil(haversine_distance_km / 22 * 60) + 12)
    else:
        mode = "cross_district_taxi"
        duration = max(50, math.ceil(haversine_distance_km / 28 * 60) + 15)

    source = "haversine_estimated"
    distance_km = haversine_distance_km
    amap_estimate = (
        route_service.estimate_segment(
            previous,
            current,
            fallback_distance_km=haversine_distance_km,
        )
        if route_service
        else None
    )
    if amap_estimate:
        distance_km = amap_estimate.distance_km
        duration = amap_estimate.duration_minutes
        source = amap_estimate.source
        polyline = amap_estimate.polyline
    else:
        polyline = []

    return {
        "from": previous["name"],
        "to": current["name"],
        "from_item_id": previous["id"],
        "to_item_id": current["id"],
        "from_id": previous["id"],
        "to_id": current["id"],
        "distance_km": round(distance_km, 2),
        "transport_mode": mode,
        "duration_minutes": int(duration),
        "source": source,
        "polyline": polyline,
        "fallback_distance_km": round(haversine_distance_km, 2),
    }


def _route_mode(route_segments: list[dict[str, Any]]) -> str:
    """根据路线段来源判断整条路线的数据源。"""

    if not route_segments:
        return "no_route_needed"
    sources = {str(segment.get("source")) for segment in route_segments}
    if any(source.startswith("amap_") for source in sources):
        return "amap_corrected"
    return "haversine_estimated"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """用 Haversine 公式估算两个经纬度点的球面距离。"""

    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _total_duration_for_state(
    state: PlanState,
    stay_minutes: list[int],
    route_minutes: int,
    duration_limit: int,
) -> int:
    """计算方案总时长，并保留测试用强制超时分支。"""

    if state.get("force_duration_exceeded") and state.get("replanning_count", 0) <= 1:
        return duration_limit + 45
    return sum(stay_minutes) + route_minutes


def _fit_stay_minutes(
    items: list[dict[str, Any]],
    route_minutes: int,
    duration_limit: int,
) -> list[int]:
    """在不低于业务最小停留时长的前提下，压缩方案到时间窗口内。

    例如电影 + 晚餐因为路程多出 5-10 分钟时，不应该直接失败；
    可以把餐厅或娱乐停留时长小幅压缩。若已经压到最小仍超时，则交给 Verifier。
    """

    stays = [int(item.get("estimated_duration_minutes", 60)) for item in items]
    overflow = sum(stays) + route_minutes - duration_limit
    if overflow <= 0:
        return stays

    # 先压缩非餐厅，再压缩餐厅，尽量保留用餐体验。
    order = sorted(
        range(len(items)),
        key=lambda index: (items[index].get("category") == "poi_restaurant", -stays[index]),
    )
    for index in order:
        minimum = _minimum_stay_minutes(str(items[index].get("category", "")))
        reducible = max(0, stays[index] - minimum)
        if reducible <= 0:
            continue
        cut = min(reducible, overflow)
        stays[index] -= cut
        overflow -= cut
        if overflow <= 0:
            break
    return stays


def _minimum_stay_minutes(category: str) -> int:
    """每类 POI 的最小可接受停留时长。"""

    return {
        "poi_restaurant": 60,
        "poi_entertainment": 90,
        "poi_activity": 75,
        "poi_attraction": 60,
        "poi_shopping": 45,
        "poi_fitness": 60,
        "poi_beauty": 60,
    }.get(category, 45)


def _build_timeline(
    items: list[dict[str, Any]],
    route_segments: list[dict[str, Any]],
    start_time: str,
    stay_minutes_by_item: list[int],
) -> list[dict[str, Any]]:
    """构造带开始/结束时间、停留时长和交通信息的 PlanSlot 时间线。"""

    current_time = _parse_time(start_time)
    timeline: list[dict[str, Any]] = []
    has_origin_segment = len(route_segments) == len(items)
    for index, item in enumerate(items):
        travel_minutes = 0
        transport_mode = "start"
        distance_km = 0.0
        if has_origin_segment or index > 0:
            segment_index = index if has_origin_segment else index - 1
            segment = route_segments[segment_index]
            travel_minutes = int(segment["duration_minutes"])
            transport_mode = str(segment["transport_mode"])
            distance_km = float(segment["distance_km"])
            current_time += timedelta(minutes=travel_minutes)

        stay_minutes = stay_minutes_by_item[index]
        start = current_time
        end = current_time + timedelta(minutes=stay_minutes)
        timeline.append({
            "order": index + 1,
            "slot_type": _slot_type_for_category(str(item.get("category", ""))),
            "poi_id": item["id"],
            "title": item["name"],
            "category": item["category"],
            "address": item["address"],
            "start_time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M"),
            "stay_minutes": stay_minutes,
            "travel_from_previous_minutes": travel_minutes,
            "transport_mode": transport_mode,
            "distance_from_previous_km": distance_km,
        })
        current_time = end
    return timeline


def _parse_time(value: str) -> datetime:
    """把 HH:MM 解析成当天虚拟 datetime，便于做分钟级加减。"""

    try:
        return datetime.strptime(value, "%H:%M")
    except ValueError:
        return datetime.strptime("14:00", "%H:%M")


def _slot_type_for_category(category: str) -> str:
    """把 POI 类别转成时间线槽位类型。"""

    return {
        "poi_restaurant": "restaurant",
        "poi_activity": "activity",
        "poi_attraction": "attraction",
        "poi_shopping": "shopping",
        "poi_fitness": "fitness",
        "poi_entertainment": "entertainment",
        "poi_beauty": "lifestyle",
    }.get(category, "poi")


def _estimate_budget(items: list[dict[str, Any]]) -> int:
    """根据价格等级粗略估算方案预算。

    当前数据库缺少统一精确价格，因此先按价格等级估算。Gate 5/6 会继续把预算适配
    纳入校验和排序。
    """

    return sum(_estimate_item_budget(item) for item in items)


def _fit_summary(
    *,
    items: list[dict[str, Any]],
    route_minutes: int,
    total_duration: int,
    duration_limit: int,
    estimated_budget: int,
    budget: int,
) -> dict[str, Any]:
    """生成方案可执行性摘要，供前端和 Response Generator 直接展示。"""

    return {
        "slot_count": len(items),
        "route_minutes": route_minutes,
        "duration_fit": "good" if total_duration <= duration_limit else "over_time",
        "budget_fit": "good" if estimated_budget <= budget else "over_budget",
        "movement_level": _movement_level(route_minutes),
        "summary": (
            f"{len(items)} 个地点，交通约 {route_minutes} 分钟，"
            f"总时长 {total_duration}/{duration_limit} 分钟，预算 {estimated_budget}/{budget} 元。"
        ),
    }


def _origin_from_user_profile(user_profile: dict[str, Any]) -> dict[str, Any] | None:
    """从用户画像中读取起点坐标，支持 start_location/origin/start_poi 三种字段名。

    只有调用方明确提供经纬度时才加入起点路段；否则不编造用户出发位置。
    """

    raw = (
        user_profile.get("start_location")
        or user_profile.get("origin")
        or user_profile.get("start_poi")
    )
    if not isinstance(raw, dict):
        return None
    try:
        lat = float(raw.get("lat"))
        lon = float(raw.get("lon"))
    except (TypeError, ValueError):
        return None
    return {
        "id": str(raw.get("id") or "origin"),
        "name": str(raw.get("name") or "出发点"),
        "category": "origin",
        "subcategory": "origin",
        "lat": lat,
        "lon": lon,
        "address": str(raw.get("address") or "用户出发点"),
    }


def _route_harness_logs(route_service: AmapRouteService | None) -> list[str]:
    """把高德 ToolHarness 调用摘要写入 DAG logs，供 SSE/Trace 展示。"""

    if route_service is None:
        return []
    logs: list[str] = []
    for entry in route_service.call_log[-6:]:
        logs.append(
            "ToolHarness amap.route.estimate_segment: "
            f"source={entry.get('source')}, success={entry.get('success')}, "
            f"latency_ms={entry.get('latency_ms')}"
        )
    return logs


def _movement_level(route_minutes: int) -> str:
    """把交通分钟数转成用户能理解的移动强度。"""

    if route_minutes <= 15:
        return "low"
    if route_minutes <= 35:
        return "medium"
    return "high"


def _estimate_item_budget(item: dict[str, Any]) -> int:
    """按类别和价格等级估算单点预算。"""

    avg_price = item.get("avg_price")
    try:
        if avg_price not in (None, "") and float(avg_price) > 0:
            return round(float(avg_price))
    except TypeError, ValueError:
        pass

    category = str(item.get("category", ""))
    price_level = str(item.get("price_level", "unknown"))
    table = {
        "poi_entertainment": {"low": 50, "medium": 80, "high": 160, "unknown": 80},
        "poi_restaurant": {"low": 60, "medium": 120, "high": 220, "unknown": 100},
        "poi_beauty": {"low": 80, "medium": 160, "high": 280, "unknown": 150},
        "poi_fitness": {"low": 50, "medium": 100, "high": 180, "unknown": 80},
    }
    default = {"low": 60, "medium": 140, "high": 260, "unknown": 120}
    return table.get(category, default).get(price_level, table.get(category, default)["unknown"])


def _title_for_template(planning_template: str) -> str:
    """把 Planner 模板转成用户可理解的方案标题。"""

    titles = {
        "meal_only": "本地餐厅推荐方案",
        "meal_plus_activity": "吃饭 + 活动本地生活方案",
        "family_half_day": "亲子半日本地生活方案",
        "friends_gathering": "朋友聚会本地生活方案",
        "entertainment_gathering": "朋友娱乐聚会方案",
        "couple_date": "情侣约会本地生活方案",
        "relaxation": "放松养生本地生活方案",
        "shopping_leisure": "购物休闲本地生活方案",
    }
    return titles.get(planning_template, "周末本地生活轻量方案")

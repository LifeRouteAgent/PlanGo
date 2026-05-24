from __future__ import annotations

from statistics import mean
from typing import Any

from app.agents.issue_utils import normalize_issues
from app.services.memory_scoring import plan_memory_fit
from app.state.plan_state import PlanState, PlanStatePatch


def ranker_node(state: PlanState) -> PlanStatePatch:
    """候选方案排序节点。

    Gate 6 开始，完整规划按“整体方案质量”排序，而不是只看 POI 数量：
    - 偏好匹配
    - 距离合理性
    - 时间可执行性
    - 评分/热度
    - 预算适配
    - 场景适配
    - warning 风险扣分

    单类推荐仍按单点推荐分排序，因为用户此时并不需要路线组合。
    """

    if state.get("intent_type") in {"category_recommend", "poi_search"}:
        return _rank_category_recommendations(state)

    scored_plans = [_attach_plan_score(plan, state) for plan in state.get("verified_plans", [])]
    ranked = sorted(
        scored_plans,
        key=lambda plan: (
            -float(plan.get("plan_score", 0)),
            int(plan.get("route_minutes", 0)),
            int(plan.get("estimated_budget", 0)),
        ),
    )
    selected = ranked[0] if ranked else {}
    return {
        "ranked_plans": ranked,
        "selected_plan": selected,
        "logs": [
            f"Ranker: ranked {len(ranked)} plans by plan_score"
            + (f", selected_score={selected.get('plan_score')}" if selected else "")
        ],
    }


def _rank_category_recommendations(state: PlanState) -> PlanStatePatch:
    """单类推荐排序。

    分类推荐没有路线组合，因此仍以单 POI 为单位排序；但排序分不再只看 score，
    也会考虑预算适配、场景适配、拥挤风险。
    """

    items = [
        _attach_item_rank_score(item)
        for group in state.get("recommended_pois", {}).values()
        for item in group
    ]
    ranked_items = sorted(
        items,
        key=lambda item: float(item.get("recommendation_score", 0)),
        reverse=True,
    )
    selected = {
        "id": "category_recommendation",
        "title": "本地生活分类推荐",
        "items": ranked_items[:8],
        "verified": True,
        "plan_score": round(
            _average([item.get("recommendation_score", 0) for item in ranked_items[:8]]), 2
        ),
    }
    return {
        "ranked_plans": [selected] if ranked_items else [],
        "selected_plan": selected if ranked_items else {},
        "logs": [f"Ranker: ranked {len(ranked_items)} recommended POIs by recommendation_score"],
    }


def _attach_plan_score(plan: dict[str, Any], state: PlanState) -> dict[str, Any]:
    """计算并挂载整体方案评分。"""

    constraints = state.get("constraints", {})
    required_slots = list(
        plan.get("required_slots") or state.get("dag_plan", {}).get("required_slots") or []
    )
    max_route_minutes = int(constraints.get("max_route_minutes", 45))
    duration_limit = int(float(constraints.get("duration_hours", 6))) * 60
    budget = int(float(constraints.get("budget", 600)))
    issues = normalize_issues(plan.get("issues", []))

    preference_match = _preference_match_score(plan, required_slots)
    distance_reasonable = _distance_score(plan, max_route_minutes)
    time_feasible = _time_score(plan, duration_limit)
    rating_heat = _rating_score(plan)
    budget_fit = _budget_score(plan, budget)
    scene_fit = _scene_score(plan)
    memory_fit = plan_memory_fit(plan, state.get("user_profile", {}))
    warning_penalty = _warning_penalty(issues)

    weighted_score = (
        0.22 * preference_match
        + 0.18 * distance_reasonable
        + 0.18 * time_feasible
        + 0.14 * rating_heat
        + 0.10 * budget_fit
        + 0.10 * scene_fit
        + 0.08 * memory_fit
    )
    plan_score = round(max(0, min(100, weighted_score * 100 - warning_penalty * 100)), 2)
    return {
        **plan,
        "plan_score": plan_score,
        "score_breakdown": {
            "preference_match": round(preference_match, 3),
            "distance_reasonable": round(distance_reasonable, 3),
            "time_feasible": round(time_feasible, 3),
            "rating_heat": round(rating_heat, 3),
            "budget_fit": round(budget_fit, 3),
            "scene_fit": round(scene_fit, 3),
            "memory_fit": round(memory_fit, 3),
            "warning_penalty": round(warning_penalty, 3),
            "issue_codes": [issue["code"] for issue in issues],
        },
    }


def _attach_item_rank_score(item: dict[str, Any]) -> dict[str, Any]:
    """为分类推荐候选计算单点排序分。"""

    score = float(item.get("score", item.get("rating", 0)) or 0)
    scene_fit = float(item.get("scene_fit", 0.7) or 0.7)
    budget_bonus = {
        "good": 0.25,
        "unknown": 0.0,
        "tight": -0.15,
        "over_budget": -0.8,
    }.get(str(item.get("budget_fit", "unknown")), 0.0)
    crowd_penalty = {
        "low": 0.1,
        "medium": -0.05,
        "high": -0.45,
    }.get(str(item.get("crowd_risk", "medium")), -0.05)
    memory_bonus = float(item.get("memory_score_adjustment", 0) or 0)
    recommendation_score = round(
        score + scene_fit * 0.5 + budget_bonus + crowd_penalty + memory_bonus, 2
    )
    return {**item, "recommendation_score": recommendation_score}


def _preference_match_score(plan: dict[str, Any], required_slots: list[str]) -> float:
    """评估方案是否覆盖 Planner 要求的核心槽位。"""

    core_slots = [slot for slot in required_slots if not str(slot).startswith("optional")]
    if not core_slots:
        return 1.0
    categories = {str(item.get("category", "")) for item in plan.get("items", [])}
    matched = sum(
        1
        for slot in core_slots
        if any(_category_matches_slot(category, slot) for category in categories)
    )
    return matched / len(core_slots)


def _category_matches_slot(category: str, slot: str) -> bool:
    """判断统一 POI 类别是否能填充某个规划槽位。"""

    slot_map = {
        "restaurant": {"poi_restaurant"},
        "restaurant_or_tea": {"poi_restaurant", "poi_beauty"},
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


def _distance_score(plan: dict[str, Any], max_route_minutes: int) -> float:
    """路线越紧凑得分越高；超过阈值的方案通常已被 Verifier 拦截。"""

    route_minutes = float(plan.get("route_minutes", 0) or 0)
    if route_minutes <= 0:
        return 1.0
    denominator = max(1, max_route_minutes)
    return max(0.0, min(1.0, 1 - route_minutes / (denominator * 1.5)))


def _time_score(plan: dict[str, Any], duration_limit: int) -> float:
    """评估方案是否充分且不过载地使用用户时间窗口。"""

    total_duration = float(plan.get("total_duration_minutes", 0) or 0)
    if duration_limit <= 0 or total_duration <= 0:
        return 0.6
    utilization = min(1.0, total_duration / duration_limit)
    # 理想使用率在 70%-95%，太空或太满都略降权。
    if 0.7 <= utilization <= 0.95:
        return 1.0
    return max(0.55, 1 - abs(0.85 - utilization) * 0.8)


def _rating_score(plan: dict[str, Any]) -> float:
    """用 POI 评分/热度的平均值估算方案基础质量。"""

    ratings = [float(item.get("rating", 0) or 0) for item in plan.get("items", [])]
    if not ratings:
        return 0.0
    return max(0.0, min(1.0, _average(ratings) / 5))


def _budget_score(plan: dict[str, Any], budget: int) -> float:
    """预算越贴近但不超支越好；过低说明方案可能不完整。"""

    estimated = float(plan.get("estimated_budget", 0) or 0)
    if budget <= 0 or estimated <= 0:
        return 0.7
    if estimated > budget:
        return max(0.0, 1 - (estimated - budget) / budget)
    usage = estimated / budget
    if usage < 0.25:
        return 0.75
    return max(0.65, 1 - usage * 0.25)


def _scene_score(plan: dict[str, Any]) -> float:
    """方案中 POI 的平均场景适配度。"""

    scene_scores = [float(item.get("scene_fit", 0.7) or 0.7) for item in plan.get("items", [])]
    return max(0.0, min(1.0, _average(scene_scores) if scene_scores else 0.7))


def _warning_penalty(issues: list[dict[str, Any]]) -> float:
    """warning 风险扣分；error 理论上不会进入 Ranker。"""

    weights = {
        "reservation_required": 0.02,
        "open_time_unknown": 0.03,
        "queue_risk": 0.08,
        "duplicate_category": 0.06,
        "cross_district_move": 0.12,
        "weak_preference_match": 0.05,
    }
    return min(0.35, sum(weights.get(str(issue.get("code")), 0.04) for issue in issues))


def _average(values: list[Any]) -> float:
    """安全平均值工具。"""

    numbers = [float(value or 0) for value in values]
    return mean(numbers) if numbers else 0.0

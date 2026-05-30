from __future__ import annotations

from app.services.memory_scoring import attach_memory_fields
from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import (
    POI_RESTAURANT,
    price_level_budget_fit,
    recommend_poi,
    score_budget_fit,
    score_crowd_risk,
)
from app.tools.skill_registry import skill_enabled, skipped_skill_patch


def poi_restaurant_recommend_node(state: PlanState) -> PlanStatePatch:
    """餐厅美食推荐 Skill。

    餐厅推荐不再直接从用户原句里判断“周末/晚餐”等词；主路径消费
    Constraint Builder 规整后的时间、预算、人数、场景。没有结构化时间时，
    才允许使用轻量 fallback。
    """

    if not skill_enabled(state, "poi_restaurant_recommend"):
        return skipped_skill_patch("poi_restaurant_recommend")

    constraints = state.get("constraints", {})
    scenario = str(constraints.get("scenario", "unknown"))
    per_person_budget = _per_person_budget(constraints)
    items = [
        attach_memory_fields(
            recommend_poi(
                item,
                score_boost=_score_boost(item, scenario, per_person_budget, constraints),
                reason=_reason_for_restaurant(item, scenario),
                estimated_duration_minutes=_estimated_meal_duration(scenario),
                reservation_required=_reservation_required(item, constraints),
                crowd_risk=_crowd_risk(item, constraints),
                budget_fit=price_level_budget_fit(
                    str(item.get("price_level", "unknown")), per_person_budget
                ),
                scene_fit=_scene_fit(scenario),
                distance_sensitive=True,
                risk_flags=_risk_flags(item, per_person_budget, constraints),
            ),
            state.get("user_profile", {}),
        )
        for item in state.get("candidate_pois", {}).get(POI_RESTAURANT, [])
    ]
    return {
        "recommended_pois": {"restaurant": items},
        "logs": [f"Skill poi_restaurant_recommend: recommended {len(items)} POIs"],
    }


def _per_person_budget(constraints: dict) -> float | None:
    """根据总预算和人数估算餐厅人均预算。"""

    budget = constraints.get("budget")
    people_count = int(constraints.get("people_count") or 1)
    if not budget:
        return None
    return float(budget) / max(1, people_count)


def _score_boost(
    item: dict,
    scenario: str,
    per_person_budget: float | None,
    constraints: dict,
) -> float:
    """餐厅推荐分由预算适配、拥挤风险和场景适配共同决定。"""

    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    crowd_risk = _crowd_risk(item, constraints)
    return round(
        0.25
        + score_budget_fit(budget_fit)
        + score_crowd_risk(crowd_risk)
        + _scene_fit(scenario) * 0.1,
        2,
    )


def _estimated_meal_duration(scenario: str) -> int:
    """估算用餐停留时长。朋友聚会通常比普通吃饭更久。"""

    if scenario == "friends":
        return 90
    if scenario == "family":
        return 75
    return 80


def _reservation_required(item: dict, constraints: dict) -> bool:
    """结构化时间显示为高峰餐段或高评分餐厅时，建议预约。"""

    return _is_peak_meal_time(constraints) or float(item.get("rating", 0) or 0) >= 4.6


def _crowd_risk(item: dict, constraints: dict) -> str:
    """估算排队/拥挤风险。后续接入真实排队数据时替换这里。"""

    rating = float(item.get("rating", 0) or 0)
    if _is_peak_meal_time(constraints) and rating >= 4.6:
        return "high"
    if rating >= 4.4:
        return "medium"
    return "low"


def _is_peak_meal_time(constraints: dict) -> bool:
    """用结构化时间判断是否处于用餐高峰。

    只要用户没有明确给时间，就不硬塞“晚餐/周末”等约束，避免把没有说明的
    条件变成硬限制。
    """

    hour = _start_hour(constraints)
    if hour is None:
        return False
    return 11 <= hour <= 13 or 17 <= hour <= 20


def _start_hour(constraints: dict) -> int | None:
    """从结构化 start_time 中解析小时数。"""

    start_time = constraints.get("start_time")
    if not start_time:
        return None
    text = str(start_time)
    try:
        if ":" in text:
            return int(text.split(":", 1)[0][-2:])
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _scene_fit(scenario: str) -> float:
    """餐厅对多数场景都适配，朋友聚会和家庭场景略高。"""

    return {
        "friends": 0.95,
        "family": 0.85,
        "couple": 0.8,
        "unknown": 0.7,
    }.get(scenario, 0.7)


def _reason_for_restaurant(item: dict, scenario: str) -> str:
    """生成可解释推荐理由，方便前端和最终响应直接展示。"""

    tags = "、".join(item.get("tags", [])[:2]) or item.get("subcategory", "餐饮")
    scene_text = {
        "friends": "适合朋友聚餐聊天",
        "family": "适合家庭用餐",
        "couple": "适合约会用餐",
    }.get(scenario, "适合作为行程餐饮锚点")
    return f"餐厅推荐：{scene_text}，标签匹配 {tags}，建议提前确认排队或订位。"


def _risk_flags(item: dict, per_person_budget: float | None, constraints: dict) -> list[str]:
    """给 Verifier 提供结构化风险信号。"""

    flags: list[str] = []
    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    if budget_fit == "over_budget":
        flags.append("budget_risk")
    if _crowd_risk(item, constraints) == "high":
        flags.append("queue_risk")
    if item.get("open_status") == "unknown":
        flags.append("open_time_unknown")
    return flags

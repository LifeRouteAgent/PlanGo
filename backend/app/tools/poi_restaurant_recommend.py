from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import (
    POI_RESTAURANT,
    price_level_budget_fit,
    recommend_poi,
    score_budget_fit,
    score_crowd_risk,
)


def poi_restaurant_recommend_node(state: PlanState) -> PlanStatePatch:
    """餐厅美食推荐 Skill。

    餐厅是本地生活规划里的核心锚点，不能只按评分排序。
    这里先做轻量规则：
    - 用总预算 / 人数估算人均预算适配。
    - 晚餐、周末、高评分餐厅提高排队风险。
    - 家庭/朋友/情侣场景分别给不同场景适配分。
    - 输出预计用餐时长、是否建议预约、拥挤风险和预算适配。
    """

    constraints = state.get("constraints", {})
    scenario = str(constraints.get("scenario", "unknown"))
    per_person_budget = _per_person_budget(constraints)
    items = [
        recommend_poi(
            item,
            score_boost=_score_boost(item, scenario, per_person_budget, state["user_query"]),
            reason=_reason_for_restaurant(item, scenario),
            estimated_duration_minutes=_estimated_meal_duration(scenario),
            reservation_required=_reservation_required(item, state["user_query"]),
            crowd_risk=_crowd_risk(item, state["user_query"]),
            budget_fit=price_level_budget_fit(
                str(item.get("price_level", "unknown")), per_person_budget
            ),
            scene_fit=_scene_fit(scenario),
            distance_sensitive=True,
            risk_flags=_risk_flags(item, per_person_budget, state["user_query"]),
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
    query: str,
) -> float:
    """餐厅推荐分由基础权重、预算适配、拥挤风险和场景适配共同决定。"""

    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    crowd_risk = _crowd_risk(item, query)
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


def _reservation_required(item: dict, query: str) -> bool:
    """周末、晚餐和高评分餐厅都建议预约。"""

    return (
        "周末" in query
        or "晚上" in query
        or "晚餐" in query
        or float(item.get("rating", 0) or 0) >= 4.6
    )


def _crowd_risk(item: dict, query: str) -> str:
    """估算排队/拥挤风险。后续接入真实排队数据时替换这里。"""

    rating = float(item.get("rating", 0) or 0)
    if ("周末" in query or "晚上" in query or "晚餐" in query) and rating >= 4.6:
        return "high"
    if rating >= 4.4:
        return "medium"
    return "low"


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


def _risk_flags(item: dict, per_person_budget: float | None, query: str) -> list[str]:
    """给 Verifier 提供结构化风险信号。"""

    flags: list[str] = []
    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    if budget_fit == "over_budget":
        flags.append("budget_risk")
    if _crowd_risk(item, query) == "high":
        flags.append("queue_risk")
    if item.get("open_status") == "unknown":
        flags.append("open_time_unknown")
    return flags

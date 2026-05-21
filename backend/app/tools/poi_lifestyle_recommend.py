from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import (
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    price_level_budget_fit,
    recommend_poi,
    score_budget_fit,
)
from app.tools.skill_registry import skill_enabled, skipped_skill_patch


def poi_lifestyle_recommend_node(state: PlanState) -> PlanStatePatch:
    """生活方式推荐 Skill。

    覆盖健身、娱乐、按摩美容等非餐饮类本地生活场景。
    这些类别的业务约束差异很大：
    - 娱乐通常有固定场次或包间人数，适合朋友/情侣。
    - 健身只在用户明确偏运动时更适合进入方案。
    - 美容养生更适合慢节奏放松，通常需要预约。
    """

    if not skill_enabled(state, "poi_lifestyle_recommend"):
        return skipped_skill_patch("poi_lifestyle_recommend")

    categories = (POI_FITNESS, POI_ENTERTAINMENT, POI_BEAUTY)
    constraints = state.get("constraints", {})
    scenario = str(constraints.get("scenario", "unknown"))
    per_person_budget = _per_person_budget(constraints)
    items: list[dict] = []
    for category in categories:
        for item in state.get("candidate_pois", {}).get(category, []):
            items.append(
                recommend_poi(
                    item,
                    score_boost=_score_boost(
                        item, state["user_query"], scenario, per_person_budget
                    ),
                    reason=_reason_for_lifestyle(item, scenario),
                    estimated_duration_minutes=_estimated_duration(item),
                    reservation_required=_reservation_required(item),
                    crowd_risk=_crowd_risk(item),
                    budget_fit=price_level_budget_fit(
                        str(item.get("price_level", "unknown")), per_person_budget
                    ),
                    scene_fit=_scene_fit(item, state["user_query"], scenario),
                    distance_sensitive=True,
                    risk_flags=_risk_flags(item, state["user_query"], per_person_budget),
                )
            )
    return {
        "recommended_pois": {"lifestyle": items},
        "logs": [f"Skill poi_lifestyle_recommend: recommended {len(items)} POIs"],
    }


def _per_person_budget(constraints: dict) -> float | None:
    """生活方式项目通常按人计价，先用人均预算粗略判断。"""

    budget = constraints.get("budget")
    people_count = int(constraints.get("people_count") or 1)
    if not budget:
        return None
    return float(budget) / max(1, people_count)


def _estimated_duration(item: dict) -> int:
    """按娱乐/健身/美容养生类别估算停留时长。"""

    category = item.get("category")
    if category == POI_ENTERTAINMENT:
        return 120
    if category == POI_FITNESS:
        return 90
    if category == POI_BEAUTY:
        return 90
    return 75


def _reservation_required(item: dict) -> bool:
    """娱乐包间、健身场地和美容养生通常都建议预约。"""

    return item.get("category") in {POI_ENTERTAINMENT, POI_FITNESS, POI_BEAUTY}


def _crowd_risk(item: dict) -> str:
    """高评分娱乐和美容养生点位按中等风险处理，后续可接实时库存。"""

    if float(item.get("rating", 0) or 0) >= 4.6:
        return "medium"
    return "low"


def _scene_fit(item: dict, query: str, scenario: str) -> float:
    """生活方式类强依赖用户是否明确表达了偏好。"""

    category = item.get("category")
    if category == POI_FITNESS:
        return (
            0.9
            if any(keyword in query for keyword in ("健身", "运动", "瑜伽", "羽毛球", "爬山"))
            else 0.45
        )
    if category == POI_ENTERTAINMENT:
        return 0.9 if scenario in {"friends", "couple"} else 0.65
    if category == POI_BEAUTY:
        return (
            0.9
            if any(keyword in query for keyword in ("放松", "按摩", "养生", "足疗", "美容"))
            else 0.6
        )
    return 0.6


def _score_boost(
    item: dict,
    query: str,
    scenario: str,
    per_person_budget: float | None,
) -> float:
    """生活方式推荐分由偏好明确性、预算和场景适配共同决定。"""

    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    return round(0.12 + score_budget_fit(budget_fit) + _scene_fit(item, query, scenario) * 0.15, 2)


def _reason_for_lifestyle(item: dict, scenario: str) -> str:
    """生成生活方式推荐理由。"""

    category = item.get("category")
    duration = _estimated_duration(item)
    if category == POI_ENTERTAINMENT:
        scene_text = "适合朋友聚会或约会后的娱乐时间"
    elif category == POI_FITNESS:
        scene_text = "适合明确想运动的本地生活安排"
    elif category == POI_BEAUTY:
        scene_text = "适合慢节奏放松和养生安排"
    else:
        scene_text = "适合作为餐前或餐后的轻量体验"
    if scenario == "family" and category != POI_ENTERTAINMENT:
        scene_text += "，但需要确认同行成人是否都参与"
    return f"生活方式推荐：{scene_text}，预计停留 {duration} 分钟，建议提前预约。"


def _risk_flags(item: dict, query: str, per_person_budget: float | None) -> list[str]:
    """给 Verifier 提供生活方式类风险信号。"""

    flags: list[str] = []
    if _reservation_required(item):
        flags.append("reservation_required")
    if item.get("category") == POI_FITNESS and not any(
        keyword in query for keyword in ("健身", "运动", "瑜伽", "羽毛球", "爬山")
    ):
        flags.append("weak_preference_match")
    if (
        price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
        == "over_budget"
    ):
        flags.append("budget_risk")
    if item.get("open_status") == "unknown":
        flags.append("open_time_unknown")
    return flags

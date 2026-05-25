from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.services.memory_scoring import attach_memory_fields
from app.tools.poi_schema import (
    POI_ACTIVITY,
    price_level_budget_fit,
    recommend_poi,
    score_budget_fit,
)
from app.tools.skill_registry import skill_enabled, skipped_skill_patch


def poi_activity_recommend_node(state: PlanState) -> PlanStatePatch:
    """活动票券/体验推荐 Skill。

    活动类 POI 的关键不是单点评分，而是能不能放进用户时间窗口：
    - 展览/手作/票券通常需要预约或购票。
    - 活动停留时长要小于总时间窗口。
    - 朋友、亲子、情侣场景对活动的适配不同。
    """

    if not skill_enabled(state, "poi_activity_recommend"):
        return skipped_skill_patch("poi_activity_recommend")

    constraints = state.get("constraints", {})
    duration_limit = int(float(constraints.get("duration_hours", 10))) * 60
    per_person_budget = _per_person_budget(constraints)
    scenario = str(constraints.get("scenario", "unknown"))
    items = [
        attach_memory_fields(
            recommend_poi(
                item,
                score_boost=_score_boost(item, duration_limit, per_person_budget, scenario),
                reason=_reason_for_activity(item, scenario),
                estimated_duration_minutes=_estimated_activity_duration(item),
                reservation_required=True,
                crowd_risk=_crowd_risk(item),
                budget_fit=price_level_budget_fit(
                    str(item.get("price_level", "unknown")), per_person_budget
                ),
                scene_fit=_scene_fit(item, scenario),
                distance_sensitive=True,
                risk_flags=_risk_flags(item, duration_limit, per_person_budget),
            ),
            state.get("user_profile", {}),
        )
        for item in state.get("candidate_pois", {}).get(POI_ACTIVITY, [])
    ]
    return {
        "recommended_pois": {"activity": items},
        "logs": [f"Skill poi_activity_recommend: recommended {len(items)} POIs"],
    }


def _per_person_budget(constraints: dict) -> float | None:
    """把总预算折算成活动人均预算。"""

    budget = constraints.get("budget")
    people_count = int(constraints.get("people_count") or 1)
    if not budget:
        return None
    return float(budget) / max(1, people_count)


def _estimated_activity_duration(item: dict) -> int:
    """按活动标签估算停留时长。"""

    text = " ".join([str(item.get("subcategory", "")), *item.get("tags", [])])
    if any(keyword in text for keyword in ("展览", "博物馆", "演出")):
        return 120
    if any(keyword in text for keyword in ("手作", "体验", "课程")):
        return 90
    return 75


def _score_boost(
    item: dict,
    duration_limit: int,
    per_person_budget: float | None,
    scenario: str,
) -> float:
    """活动推荐分重点考虑时间可放入性、预算和场景匹配。"""

    duration = _estimated_activity_duration(item)
    time_fit = 0.15 if duration <= duration_limit * 0.6 else -0.25
    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    return round(
        0.2 + time_fit + score_budget_fit(budget_fit) + _scene_fit(item, scenario) * 0.12, 2
    )


def _crowd_risk(item: dict) -> str:
    """活动热门程度越高，越需要保守估算拥挤风险。"""

    return "medium" if float(item.get("rating", 0) or 0) >= 4.5 else "low"


def _scene_fit(item: dict, scenario: str) -> float:
    """根据同行关系判断活动适配度。"""

    text = " ".join([str(item.get("subcategory", "")), *item.get("tags", [])])
    if scenario == "family" and any(
        keyword in text for keyword in ("亲子", "儿童", "博物馆", "公园")
    ):
        return 0.95
    if scenario == "friends" and any(
        keyword in text for keyword in ("体验", "手作", "展览", "活动")
    ):
        return 0.9
    if scenario == "couple" and any(keyword in text for keyword in ("展览", "手作", "演出")):
        return 0.85
    return 0.7


def _reason_for_activity(item: dict, scenario: str) -> str:
    """生成活动推荐理由。"""

    duration = _estimated_activity_duration(item)
    scenario_text = {
        "family": "适合作为亲子时间块",
        "friends": "适合朋友互动体验",
        "couple": "适合约会中的体验活动",
    }.get(scenario, "适合作为本地生活体验活动")
    return f"活动推荐：{scenario_text}，预计停留 {duration} 分钟，建议提前确认票务或预约。"


def _risk_flags(item: dict, duration_limit: int, per_person_budget: float | None) -> list[str]:
    """给 Verifier 提供活动类风险信号。"""

    flags: list[str] = ["reservation_required"]
    if _estimated_activity_duration(item) > duration_limit:
        flags.append("duration_risk")
    if (
        price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
        == "over_budget"
    ):
        flags.append("budget_risk")
    if item.get("open_status") == "unknown":
        flags.append("open_time_unknown")
    return flags

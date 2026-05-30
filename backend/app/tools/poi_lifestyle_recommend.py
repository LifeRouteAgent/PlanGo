from __future__ import annotations

from app.services.memory_scoring import attach_memory_fields
from app.services.semantic_constraints import (
    has_semantic_intent,
    item_matches_keywords,
    semantic_keywords,
    semantic_types,
)
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

    覆盖健身、娱乐、按摩美容等非餐饮本地生活场景。推荐主逻辑优先消费
    LLM 提取出的 `activity_intents / preference_keywords`，避免在 Skill 内直接
    判断“唱歌/按摩/麻将”等自然语言关键词。只有 LLM 字段缺失时才走规则兜底。
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
                attach_memory_fields(
                    recommend_poi(
                        item,
                        score_boost=_score_boost(
                            item, constraints, state["user_query"], scenario, per_person_budget
                        ),
                        reason=_reason_for_lifestyle(item, scenario),
                        estimated_duration_minutes=_estimated_duration(item),
                        reservation_required=_reservation_required(item),
                        crowd_risk=_crowd_risk(item),
                        budget_fit=price_level_budget_fit(
                            str(item.get("price_level", "unknown")), per_person_budget
                        ),
                        scene_fit=_scene_fit(item, constraints, state["user_query"], scenario),
                        distance_sensitive=True,
                        risk_flags=_risk_flags(
                            item, constraints, state["user_query"], per_person_budget
                        ),
                    ),
                    state.get("user_profile", {}),
                )
            )
    return {
        "recommended_pois": {"lifestyle": items},
        "logs": [f"Skill poi_lifestyle_recommend: recommended {len(items)} POIs"],
    }


def _per_person_budget(constraints: dict) -> float | None:
    """按人数估算生活方式项目的人均预算。"""

    budget = constraints.get("budget")
    people_count = int(constraints.get("people_count") or 1)
    if not budget:
        return None
    return float(budget) / max(1, people_count)


def _estimated_duration(item: dict) -> int:
    """按类别估算停留时长。"""

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
    """高评分生活方式 POI 按中等拥挤风险处理。"""

    if float(item.get("rating", 0) or 0) >= 4.6:
        return "medium"
    return "low"


def _scene_fit(item: dict, constraints: dict, query: str, scenario: str) -> float:
    """计算生活方式 POI 与本轮语义偏好的适配度。

    主路径消费 LLM 结构化字段；只有 LLM 未给出语义字段时，才用旧关键词兜底。
    """

    category = item.get("category")
    types = semantic_types(constraints)
    keywords = semantic_keywords(constraints)
    has_llm_semantics = has_semantic_intent(constraints)
    if category == POI_FITNESS:
        if types & {"fitness", "sport", "yoga", "badminton", "climbing", "gym"}:
            return 0.95 if item_matches_keywords(item, keywords) or not keywords else 0.8
        if has_llm_semantics:
            return 0.45
        return 0.9 if any(
            keyword in query for keyword in ("健身", "运动", "瑜伽", "羽毛球", "爬山")
        ) else 0.45
    if category == POI_ENTERTAINMENT:
        if types & {
            "ktv",
            "mahjong",
            "cards",
            "chess_cards",
            "board_game",
            "escape_room",
            "cinema",
        }:
            return 0.95 if item_matches_keywords(item, keywords) or not keywords else 0.75
        return 0.9 if scenario in {"friends", "couple"} else 0.65
    if category == POI_BEAUTY:
        if types & {"massage", "spa", "beauty", "foot_bath", "nail"}:
            return 0.95 if item_matches_keywords(item, keywords) or not keywords else 0.8
        if has_llm_semantics:
            return 0.55
        return 0.9 if any(
            keyword in query for keyword in ("放松", "按摩", "养生", "足疗", "美容")
        ) else 0.6
    return 0.6


def _score_boost(
    item: dict,
    constraints: dict,
    query: str,
    scenario: str,
    per_person_budget: float | None,
) -> float:
    """由语义适配、预算适配和基础分共同决定生活方式推荐分。"""

    budget_fit = price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
    return round(
        0.12
        + score_budget_fit(budget_fit)
        + _scene_fit(item, constraints, query, scenario) * 0.15,
        2,
    )


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


def _risk_flags(
    item: dict,
    constraints: dict,
    query: str,
    per_person_budget: float | None,
) -> list[str]:
    """给 Verifier 提供生活方式类风险信号。"""

    flags: list[str] = []
    if _reservation_required(item):
        flags.append("reservation_required")
    if item.get("category") == POI_FITNESS:
        types = semantic_types(constraints)
        if has_semantic_intent(constraints):
            if not (types & {"fitness", "sport", "yoga", "badminton", "climbing", "gym"}):
                flags.append("weak_preference_match")
        elif not any(keyword in query for keyword in ("健身", "运动", "瑜伽", "羽毛球", "爬山")):
            flags.append("weak_preference_match")
    if (
        price_level_budget_fit(str(item.get("price_level", "unknown")), per_person_budget)
        == "over_budget"
    ):
        flags.append("budget_risk")
    if item.get("open_status") == "unknown":
        flags.append("open_time_unknown")
    return flags

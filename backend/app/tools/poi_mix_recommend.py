from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.services.memory_scoring import attach_memory_fields
from app.tools.poi_schema import POI_ATTRACTION, POI_SHOPPING, recommend_poi
from app.tools.skill_registry import skill_enabled, skipped_skill_patch


def poi_mix_recommend_node(state: PlanState) -> PlanStatePatch:
    """景点 + 购物综合推荐 Skill。

    该 Skill 面向“行程骨架”和“低移动成本容器”：
    - 景点/公园/citywalk 适合作为 60-120 分钟的轻休闲时间块。
    - 商场/购物中心适合作为餐饮、电影、咖啡的中转容器，动线更稳。
    """

    if not skill_enabled(state, "poi_mix_recommend"):
        return skipped_skill_patch("poi_mix_recommend")

    categories = (POI_ATTRACTION, POI_SHOPPING)
    items = _score_items(state, categories)
    return {
        "recommended_pois": {"mix": items},
        "logs": [f"Skill poi_mix_recommend: recommended {len(items)} POIs"],
    }


def _score_items(state: PlanState, categories: tuple[str, ...]) -> list[dict]:
    """从多个 Collector 类别中挑选并打分。"""

    scenario = str(state.get("constraints", {}).get("scenario", "unknown"))
    result: list[dict] = []
    for category in categories:
        for item in state.get("candidate_pois", {}).get(category, []):
            result.append(
                attach_memory_fields(recommend_poi(
                    item,
                    score_boost=_score_boost(item, scenario),
                    reason=_reason_for_mix(item, scenario),
                    estimated_duration_minutes=_estimated_duration(item),
                    reservation_required=False,
                    crowd_risk=_crowd_risk(item),
                    budget_fit="good" if item.get("category") == POI_SHOPPING else "unknown",
                    scene_fit=_scene_fit(item, scenario),
                    distance_sensitive=True,
                    risk_flags=_risk_flags(item),
                ), state.get("user_profile", {}))
            )
    return result


def _estimated_duration(item: dict) -> int:
    """估算景点/购物类停留时长。"""

    if item.get("category") == POI_SHOPPING:
        return 75
    text = " ".join([str(item.get("subcategory", "")), *item.get("tags", [])])
    if any(keyword in text for keyword in ("公园", "citywalk", "城市漫步")):
        return 90
    return 120


def _score_boost(item: dict, scenario: str) -> float:
    """综合推荐更重视低压力、场景适配和是否能承接其他活动。"""

    base = 0.12
    if item.get("category") == POI_SHOPPING:
        base += 0.12
    return round(base + _scene_fit(item, scenario) * 0.1, 2)


def _crowd_risk(item: dict) -> str:
    """商场和热门景点在周末有中等拥挤风险。"""

    if item.get("category") == POI_SHOPPING:
        return "medium"
    return "medium" if float(item.get("rating", 0) or 0) >= 4.6 else "low"


def _scene_fit(item: dict, scenario: str) -> float:
    """判断景点/购物点与当前同行场景的适配度。"""

    text = " ".join([str(item.get("subcategory", "")), *item.get("tags", [])])
    if item.get("category") == POI_SHOPPING:
        return 0.9 if scenario in {"family", "friends"} else 0.75
    if scenario == "family" and any(keyword in text for keyword in ("公园", "亲子", "儿童")):
        return 0.9
    if scenario == "couple" and any(
        keyword in text for keyword in ("citywalk", "城市漫步", "公园")
    ):
        return 0.85
    return 0.7


def _reason_for_mix(item: dict, scenario: str) -> str:
    """生成景点/购物综合推荐理由。"""

    if item.get("category") == POI_SHOPPING:
        return "综合推荐：商场适合作为低移动成本容器，可承接吃饭、电影、咖啡或购物。"
    scenario_text = {
        "family": "适合低强度亲子休闲",
        "friends": "适合朋友先逛一逛再接餐饮娱乐",
        "couple": "适合约会中的散步或轻体验",
    }.get(scenario, "适合作为周末行程里的轻休闲时间块")
    return f"综合推荐：{scenario_text}，预计停留 {_estimated_duration(item)} 分钟。"


def _risk_flags(item: dict) -> list[str]:
    """给 Verifier 提供景点/购物类风险信号。"""

    flags: list[str] = []
    if _crowd_risk(item) == "medium":
        flags.append("crowd_risk")
    if item.get("open_status") == "unknown":
        flags.append("open_time_unknown")
    return flags

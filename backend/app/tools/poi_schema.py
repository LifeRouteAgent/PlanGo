from __future__ import annotations

from typing import Any

from app.state.plan_state import PoiRecord, RecommendedPoiRecord

# 七张 POI 逻辑表名。Collector 层和 DAG 配置都使用这组常量，避免字符串散落。
POI_ATTRACTION = "poi_attraction"
POI_SHOPPING = "poi_shopping"
POI_ACTIVITY = "poi_activity"
POI_RESTAURANT = "poi_restaurant"
POI_FITNESS = "poi_fitness"
POI_ENTERTAINMENT = "poi_entertainment"
POI_BEAUTY = "poi_beauty"

POI_CATEGORIES = (
    POI_ATTRACTION,
    POI_SHOPPING,
    POI_ACTIVITY,
    POI_RESTAURANT,
    POI_FITNESS,
    POI_ENTERTAINMENT,
    POI_BEAUTY,
)


def make_poi_record(
    *,
    id: str,
    name: str,
    category: str,
    subcategory: str,
    lat: float,
    lon: float,
    address: str,
    rating: float,
    price_level: str,
    open_status: str,
    tags: list[str],
) -> PoiRecord:
    """构造统一 POI 记录。

    这个函数是 Collector 的唯一出口格式。Gate 6 接入高德数据时，只需要把
    高德原始字段映射到这里，而不需要改 Skill 和 DAG。
    """

    return {
        "id": id,
        "name": name,
        "category": category,
        "subcategory": subcategory,
        "lat": lat,
        "lon": lon,
        "address": address,
        "rating": rating,
        "price_level": price_level,
        "open_status": open_status,
        "tags": tags,
    }


def recommend_poi(
    poi: dict[str, Any],
    *,
    score_boost: float,
    reason: str,
    estimated_duration_minutes: int,
    reservation_required: bool,
    crowd_risk: str,
    budget_fit: str,
    scene_fit: float,
    distance_sensitive: bool,
    risk_flags: list[str] | None = None,
) -> RecommendedPoiRecord:
    """把 Collector 候选转换成 Skill 推荐候选。

    Skill 层统一输出两类信息：
    - 推荐信息：score、reason、risk_flags。
    - 可执行性信息：预计停留时长、预约要求、拥挤风险、预算适配、场景适配、距离敏感性。

    这样 Route Planner 不需要理解每一类 POI 的业务细节，只消费稳定字段即可。
    """

    rating = float(poi.get("rating", 0) or 0)
    normalized_scene_fit = max(0.0, min(1.0, scene_fit))
    return {
        "id": str(poi["id"]),
        "name": str(poi["name"]),
        "category": str(poi["category"]),
        "subcategory": str(poi["subcategory"]),
        "lat": float(poi["lat"]),
        "lon": float(poi["lon"]),
        "address": str(poi["address"]),
        "rating": rating,
        "price_level": str(poi["price_level"]),
        "open_status": str(poi["open_status"]),
        "tags": list(poi.get("tags", [])),
        "score": round(rating + score_boost, 2),
        "reason": reason,
        "risk_flags": risk_flags or [],
        "estimated_duration_minutes": estimated_duration_minutes,
        "reservation_required": reservation_required,
        "crowd_risk": crowd_risk,
        "budget_fit": budget_fit,
        "scene_fit": normalized_scene_fit,
        "distance_sensitive": distance_sensitive,
    }


def price_level_budget_fit(price_level: str, per_person_budget: float | None) -> str:
    """把粗粒度价格等级映射成预算适配结果。

    当前数据库里各类 POI 的价格字段来源不完全一致，Collector 已经先归一成
    low/medium/high/unknown。Skill 在不知道精确人均价时，用这个粗粒度判断即可。
    """

    if price_level == "unknown" or per_person_budget is None:
        return "unknown"
    if price_level == "low":
        return "good"
    if price_level == "medium":
        return "good" if per_person_budget >= 80 else "tight"
    if price_level == "high":
        return "good" if per_person_budget >= 200 else "over_budget"
    return "unknown"


def score_budget_fit(budget_fit: str) -> float:
    """把预算适配结果转成推荐分加权。"""

    return {
        "good": 0.15,
        "tight": -0.05,
        "over_budget": -0.35,
        "unknown": 0.0,
    }.get(budget_fit, 0.0)


def score_crowd_risk(crowd_risk: str) -> float:
    """把拥挤/排队风险转成推荐分加权。"""

    return {
        "low": 0.1,
        "medium": 0.0,
        "high": -0.25,
    }.get(crowd_risk, 0.0)

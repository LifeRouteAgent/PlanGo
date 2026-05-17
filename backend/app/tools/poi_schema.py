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
    risk_flags: list[str] | None = None,
) -> RecommendedPoiRecord:
    """把 Collector 候选转换成 Skill 推荐候选。

    当前评分只是 mock 逻辑：高德数据接入后，可以替换为基于距离、偏好、价格、
    营业状态和历史反馈的排序模型。
    """

    rating = float(poi.get("rating", 0) or 0)
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
    }

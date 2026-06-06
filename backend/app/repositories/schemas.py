from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PoiRecallConstraints:
    """数据库候选召回阶段使用的轻量约束。

    这个对象只放 SQL 层真正需要的字段：位置半径、预算、评分、排除词和少量偏好词。
    复杂的场景解释、文案生成、方案排序仍留给 Skill/Route/Ranker，避免 SQL 层变成 God Object。
    """

    origin_lat: float | None = None
    origin_lon: float | None = None
    radius_km: float | None = None
    budget: float | None = None
    people_count: int = 1
    scene_type: str = "unknown"
    duration_hours: float | None = None
    movement_policy: str = "balanced_local"
    candidate_strategy: str = ""
    preference_keywords: tuple[str, ...] = field(default_factory=tuple)
    excluded_keywords: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_origin(self) -> bool:
        return self.origin_lat is not None and self.origin_lon is not None

    @property
    def per_person_budget(self) -> float | None:
        if self.budget is None or self.budget <= 0:
            return None
        return self.budget / max(1, self.people_count)

    def for_trace(self) -> dict[str, Any]:
        return {
            "origin_lat": self.origin_lat,
            "origin_lon": self.origin_lon,
            "radius_km": self.radius_km,
            "budget": self.budget,
            "people_count": self.people_count,
            "scene_type": self.scene_type,
            "duration_hours": self.duration_hours,
            "movement_policy": self.movement_policy,
            "candidate_strategy": self.candidate_strategy,
            "preference_keywords": list(self.preference_keywords),
            "excluded_keywords": list(self.excluded_keywords),
        }


@dataclass(frozen=True)
class CategorySqlSpec:
    """每张 POI 表的白名单 SQL 字段映射。"""

    table: str
    id_expr: str
    name_expr: str
    category: str
    subcategory_expr: str
    lat_expr: str
    lon_expr: str
    address_expr: str
    rating_expr: str | None
    price_expr: str | None
    open_expr: str
    tag_expr: str
    image_expr: str
    images_expr: str
    base_where: str
    order_expr: str
    filter_fields: tuple[str, ...] = ()
    tag_fields: tuple[str, ...] = ()

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.state.plan_state import PoiRecord
from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
    make_poi_record,
)


# 每个逻辑类别只允许映射到固定 SQL，避免把表名作为用户输入拼接进 SQL。
CATEGORY_QUERY_MAP: dict[str, str] = {
    POI_RESTAURANT: """
        SELECT source_id AS id, name, 'poi_restaurant' AS category,
               COALESCE(NULLIF(biz_category, ''), 'restaurant') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, cuisine_tag AS tag_text
        FROM poi_restaurant
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """,
    POI_ACTIVITY: """
        SELECT CAST(activity_id AS CHAR) AS id, title AS name, 'poi_activity' AS category,
               'activity' AS subcategory, location, address_desc AS address,
               NULL AS rating, price, available_date AS open_time,
               subtitle AS tag_text
        FROM poi_activities
        WHERE title <> '' AND location IS NOT NULL AND location <> ''
        ORDER BY updated_time DESC
        LIMIT %(limit)s
    """,
    POI_ATTRACTION: """
        SELECT CAST(id AS CHAR) AS id, name, 'poi_attraction' AS category,
               'attraction' AS subcategory, lat, lng AS lon, address,
               score AS rating, NULL AS price, JSON_EXTRACT(open_time, '$') AS open_time,
               tags AS tag_text
        FROM poi_attractions
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(score, 0) DESC, COALESCE(hot_score, 0) DESC
        LIMIT %(limit)s
    """,
    POI_SHOPPING: """
        SELECT source_id AS id, name, 'poi_shopping' AS category,
               COALESCE(NULLIF(categories, ''), 'shopping') AS subcategory,
               lat, lng AS lon, address, comment_score AS rating, NULL AS price,
               open_time_tips AS open_time, tags AS tag_text
        FROM poi_shoppings
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(comment_score, 0) DESC, COALESCE(comment_num, 0) DESC
        LIMIT %(limit)s
    """,
    POI_FITNESS: """
        SELECT source_id AS id, name, 'poi_fitness' AS category,
               COALESCE(NULLIF(fitness_tag, ''), 'fitness') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, fitness_tag AS tag_text
        FROM poi_fitness
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """,
    POI_ENTERTAINMENT: """
        SELECT source_id AS id, name, 'poi_entertainment' AS category,
               COALESCE(NULLIF(entertainment_type, ''), 'entertainment') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, entertainment_type AS tag_text
        FROM poi_entertainment
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(groupbuy_num, 0) DESC
        LIMIT %(limit)s
    """,
    POI_BEAUTY: """
        SELECT source_id AS id, name, 'poi_beauty' AS category,
               COALESCE(NULLIF(beauty_type, ''), 'beauty') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, COALESCE(service_tag, beauty_type) AS tag_text
        FROM poi_beauty
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """,
}


class PoiRepository:
    """本地 MySQL POI 仓储。

    该类只负责把不同来源表映射为统一 POI 结构，不做推荐排序。
    Skill 层仍然只消费统一字段，保持 Collector 和 Skill 解耦。
    """

    def __init__(self, *, limit_per_category: int = 30) -> None:
        self._limit_per_category = limit_per_category

    def fetch_by_categories(self, categories: Iterable[str]) -> dict[str, list[PoiRecord]]:
        """按逻辑类别批量读取 POI。

        未知类别会返回空列表，不抛异常，保证 Planner 可逐步扩展新类别。
        """

        result: dict[str, list[PoiRecord]] = {}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for category in categories:
                    sql = CATEGORY_QUERY_MAP.get(category)
                    if not sql:
                        result[category] = []
                        continue
                    cursor.execute(sql, {"limit": self._limit_per_category})
                    result[category] = [
                        self._row_to_poi(category, row) for row in cursor.fetchall()
                    ]
        return result

    def _connect(self):
        """创建 MySQL 连接。

        使用 DictCursor 是为了让字段映射更明确，避免依赖列顺序。
        """

        return pymysql.connect(
            host=settings.database_host,
            port=settings.database_port,
            user=settings.database_user,
            password=settings.database_password,
            database=settings.database_name,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=True,
        )

    def _row_to_poi(self, category: str, row: dict[str, Any]) -> PoiRecord:
        """把不同表的查询结果规范化成统一 POI 字段。"""

        lat, lon = self._parse_coordinates(row)
        return make_poi_record(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or ""),
            category=category,
            subcategory=str(row.get("subcategory") or category),
            lat=lat,
            lon=lon,
            address=str(row.get("address") or ""),
            rating=self._safe_float(row.get("rating"), default=4.0),
            price_level=self._price_level(row.get("price")),
            open_status=self._open_status(row.get("open_time")),
            tags=self._split_tags(row.get("tag_text")),
        )

    def _parse_coordinates(self, row: dict[str, Any]) -> tuple[float, float]:
        """兼容活动表的 `location=lat,lng` 和高德 POI 表的 lat/lon 字段。"""

        location = row.get("location")
        if location and "," in str(location):
            lat_text, lon_text = str(location).split(",", 1)
            return self._safe_float(lat_text), self._safe_float(lon_text)
        return self._safe_float(row.get("lat")), self._safe_float(row.get("lon"))

    def _split_tags(self, value: Any) -> list[str]:
        """把不同分隔符的标签文本转成列表。"""

        if not value:
            return []
        text = str(value)
        for separator in ("|", "，", ",", "、", ";"):
            text = text.replace(separator, " ")
        return [item.strip() for item in text.split() if item.strip()]

    def _price_level(self, value: Any) -> str:
        """把价格映射为前端和 Skill 都能理解的粗粒度价格等级。"""

        price = self._safe_float(value, default=0)
        if price <= 0:
            return "unknown"
        if price < 80:
            return "low"
        if price < 200:
            return "medium"
        return "high"

    def _open_status(self, value: Any) -> str:
        """当前只判断是否存在营业时间；真实营业中判断留给后续 Verifier。"""

        return "unknown" if not value else "open"

    def _safe_float(self, value: Any, *, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

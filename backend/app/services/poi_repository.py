from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.services.tool_harness import ToolHarness
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
    POI_RESTAURANT: (
        """
        SELECT source_id AS id, name, 'poi_restaurant' AS category,
               COALESCE(NULLIF(biz_category, ''), 'restaurant') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, cuisine_tag AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_restaurant
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_ACTIVITY: (
        """
        SELECT CAST(activity_id AS CHAR) AS id, title AS name, 'poi_activity' AS category,
               'activity' AS subcategory, location, address_desc AS address,
               NULL AS rating, price, available_date AS open_time,
               subtitle AS tag_text,
               NULL AS image_url, images AS images
        FROM poi_activities
        WHERE title <> '' AND location IS NOT NULL AND location <> ''
        ORDER BY updated_time DESC
        LIMIT %(limit)s
    """
    ),
    POI_ATTRACTION: (
        """
        SELECT CAST(id AS CHAR) AS id, name, 'poi_attraction' AS category,
               'attraction' AS subcategory, lat, lng AS lon, address,
               score AS rating, NULL AS price, JSON_EXTRACT(open_time, '$') AS open_time,
               tags AS tag_text,
               head_image AS image_url, NULL AS images
        FROM poi_attractions
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(score, 0) DESC, COALESCE(hot_score, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_SHOPPING: (
        """
        SELECT source_id AS id, name, 'poi_shopping' AS category,
               COALESCE(NULLIF(categories, ''), 'shopping') AS subcategory,
               lat, lng AS lon, address, comment_score AS rating, NULL AS price,
               open_time_tips AS open_time, tags AS tag_text,
               head_image AS image_url, images AS images
        FROM poi_shoppings
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(comment_score, 0) DESC, COALESCE(comment_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_FITNESS: (
        """
        SELECT source_id AS id, name, 'poi_fitness' AS category,
               COALESCE(NULLIF(fitness_tag, ''), 'fitness') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, fitness_tag AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_fitness
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_ENTERTAINMENT: (
        """
        SELECT source_id AS id, name, 'poi_entertainment' AS category,
               COALESCE(NULLIF(entertainment_type, ''), 'entertainment') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, entertainment_type AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_entertainment
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(groupbuy_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_BEAUTY: (
        """
        SELECT source_id AS id, name, 'poi_beauty' AS category,
               COALESCE(NULLIF(beauty_type, ''), 'beauty') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, COALESCE(service_tag, beauty_type) AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_beauty
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
}

NAME_QUERY_MAP: dict[str, str] = {
    POI_RESTAURANT: (
        """
        SELECT source_id AS id, name, 'poi_restaurant' AS category,
               COALESCE(NULLIF(biz_category, ''), 'restaurant') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, cuisine_tag AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_restaurant
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL AND name LIKE %(keyword)s
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_ACTIVITY: (
        """
        SELECT CAST(activity_id AS CHAR) AS id, title AS name, 'poi_activity' AS category,
               'activity' AS subcategory, location, address_desc AS address,
               NULL AS rating, price, available_date AS open_time,
               subtitle AS tag_text,
               NULL AS image_url, images AS images
        FROM poi_activities
        WHERE title <> '' AND location IS NOT NULL AND location <> '' AND title LIKE %(keyword)s
        ORDER BY updated_time DESC
        LIMIT %(limit)s
    """
    ),
    POI_ATTRACTION: (
        """
        SELECT CAST(id AS CHAR) AS id, name, 'poi_attraction' AS category,
               'attraction' AS subcategory, lat, lng AS lon, address,
               score AS rating, NULL AS price, JSON_EXTRACT(open_time, '$') AS open_time,
               tags AS tag_text,
               head_image AS image_url, NULL AS images
        FROM poi_attractions
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL AND name LIKE %(keyword)s
        ORDER BY
            CASE WHEN name = %(exact_keyword)s THEN 0 ELSE 1 END,
            COALESCE(score, 0) DESC,
            COALESCE(hot_score, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_SHOPPING: (
        """
        SELECT source_id AS id, name, 'poi_shopping' AS category,
               COALESCE(NULLIF(categories, ''), 'shopping') AS subcategory,
               lat, lng AS lon, address, comment_score AS rating, NULL AS price,
               open_time_tips AS open_time, tags AS tag_text,
               head_image AS image_url, images AS images
        FROM poi_shoppings
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL AND name LIKE %(keyword)s
        ORDER BY COALESCE(comment_score, 0) DESC, COALESCE(comment_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_FITNESS: (
        """
        SELECT source_id AS id, name, 'poi_fitness' AS category,
               COALESCE(NULLIF(fitness_tag, ''), 'fitness') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, fitness_tag AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_fitness
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL AND name LIKE %(keyword)s
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_ENTERTAINMENT: (
        """
        SELECT source_id AS id, name, 'poi_entertainment' AS category,
               COALESCE(NULLIF(entertainment_type, ''), 'entertainment') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, entertainment_type AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_entertainment
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL AND name LIKE %(keyword)s
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(groupbuy_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
    POI_BEAUTY: (
        """
        SELECT source_id AS id, name, 'poi_beauty' AS category,
               COALESCE(NULLIF(beauty_type, ''), 'beauty') AS subcategory,
               lat, lng AS lon, address, rating, cost AS price,
               open_time, COALESCE(service_tag, beauty_type) AS tag_text,
               head_image AS image_url, photos AS images
        FROM poi_beauty
        WHERE name <> '' AND lat IS NOT NULL AND lng IS NOT NULL AND name LIKE %(keyword)s
        ORDER BY COALESCE(rating, 0) DESC, COALESCE(favorite_num, 0) DESC
        LIMIT %(limit)s
    """
    ),
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

        category_list = list(categories)
        harness = ToolHarness(
            name="database.poi.fetch_by_categories",
            timeout_seconds=8,
            max_retries=1,
            fallback=lambda: {category: [] for category in category_list},
        )
        result = harness.run_request(
            {
                "tool_name": "database.poi.fetch_by_categories",
                "risk_level": 1,
                "params": {"categories": category_list, "limit": self._limit_per_category},
            },
            self._fetch_by_categories_once,
            category_list,
        )
        data = result.get("data")
        return (
            data
            if result.get("success") and isinstance(data, dict)
            else {category: [] for category in category_list}
        )

    def fetch_by_name_keywords(
        self, keywords: Iterable[str], *, categories: Iterable[str] | None = None
    ) -> dict[str, list[PoiRecord]]:
        """按用户明确点名的地点关键词检索 POI。

        只使用固定 SQL 模板和参数化 LIKE，避免把用户输入拼进表名或 SQL 结构。
        返回仍按统一 POI category 分组，方便 Collector 合并到候选池。
        """

        keyword_list = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
        category_list = list(categories or NAME_QUERY_MAP.keys())
        harness = ToolHarness(
            name="database.poi.fetch_by_name_keywords",
            timeout_seconds=8,
            max_retries=1,
            fallback=lambda: {category: [] for category in category_list},
        )
        result = harness.run_request(
            {
                "tool_name": "database.poi.fetch_by_name_keywords",
                "risk_level": 1,
                "params": {"keywords": keyword_list, "categories": category_list},
            },
            self._fetch_by_name_keywords_once,
            keyword_list,
            category_list,
        )
        data = result.get("data")
        return (
            data
            if result.get("success") and isinstance(data, dict)
            else {category: [] for category in category_list}
        )

    def _fetch_by_categories_once(self, categories: Iterable[str]) -> dict[str, list[PoiRecord]]:
        """执行一次真实数据库读取，外层由 ToolHarness 负责 timeout/retry/fallback。"""

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

    def _fetch_by_name_keywords_once(
        self,
        keywords: Iterable[str],
        categories: Iterable[str],
    ) -> dict[str, list[PoiRecord]]:
        """执行一次按名称关键词检索。"""

        result: dict[str, list[PoiRecord]] = {category: [] for category in categories}
        if not keywords:
            return result
        seen_ids: set[tuple[str, str]] = set()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for category in categories:
                    sql = NAME_QUERY_MAP.get(category)
                    if not sql:
                        continue
                    for keyword in keywords:
                        cursor.execute(
                            sql,
                            {
                                "keyword": f"%{keyword}%",
                                "exact_keyword": keyword,
                                "limit": max(3, min(self._limit_per_category, 10)),
                            },
                        )
                        for row in cursor.fetchall():
                            poi = self._row_to_poi(category, row)
                            key = (category, poi["id"])
                            if key in seen_ids:
                                continue
                            seen_ids.add(key)
                            result.setdefault(category, []).append(poi)
        return result

    def table_counts(self) -> dict[str, int]:
        """读取七张 POI 表的当前行数。

        该方法只用于健康检查和前端展示，不参与推荐流程，避免一次规划请求额外做
        聚合统计影响响应时间。
        """

        harness = ToolHarness(
            name="database.poi.table_counts",
            timeout_seconds=5,
            max_retries=1,
            fallback=lambda: {},
        )
        result = harness.run_request(
            {"tool_name": "database.poi.table_counts", "risk_level": 1, "params": {}},
            self._table_counts_once,
        )
        data = result.get("data")
        return data if result.get("success") and isinstance(data, dict) else {}

    def _table_counts_once(self) -> dict[str, int]:
        """执行一次真实表行数统计。"""

        table_names = {
            POI_RESTAURANT: "poi_restaurant",
            POI_ACTIVITY: "poi_activities",
            POI_ATTRACTION: "poi_attractions",
            POI_SHOPPING: "poi_shoppings",
            POI_FITNESS: "poi_fitness",
            POI_ENTERTAINMENT: "poi_entertainment",
            POI_BEAUTY: "poi_beauty",
        }
        counts: dict[str, int] = {}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for category, table_name in table_names.items():
                    cursor.execute(f"SELECT COUNT(*) AS count_value FROM {table_name}")
                    row = cursor.fetchone()
                    counts[category] = int(row["count_value"])
        return counts

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
        record = make_poi_record(
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
        price = self._safe_float(row.get("price"), default=0)
        if price > 0:
            record["avg_price"] = price
        images = self._split_images(row.get("images"))
        image_url = self._first_image(row.get("image_url")) or (images[0] if images else "")
        if image_url:
            record["image_url"] = image_url
        if images:
            record["images"] = images
        return record

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

    def _first_image(self, value: Any) -> str:
        """从数据库图片字段中取第一张可展示图片。"""

        images = self._split_images(value)
        return images[0] if images else ""

    def _split_images(self, value: Any) -> list[str]:
        """兼容 URL、JSON 数组、对象数组和分隔字符串形式的图片字段。

        数据库里不同 POI 表的图片字段来源不同：有的表是 `head_image` 单图，
        有的表是 `photos/images` 多图。Collector 在这里统一成前端可直接消费的
        `images: list[str]`，方案卡片再从行程 POI 中顺序选择第一张可用图做头图。
        """

        collected: list[str] = []

        def add_image(item: Any) -> None:
            if not item:
                return
            if isinstance(item, str):
                text = item.strip().strip('"').strip("'")
                if text:
                    collected.append(text)
                return
            if isinstance(item, dict):
                for key in (
                    "url",
                    "image",
                    "image_url",
                    "image_url_host",
                    "photo",
                    "pic",
                    "src",
                    "cover",
                    "head_image",
                ):
                    add_image(item.get(key))
                return
            if isinstance(item, list | tuple):
                for child in item:
                    add_image(child)

        if isinstance(value, list | tuple | dict):
            add_image(value)
        elif value:
            text = str(value).strip()
            parsed = None
            if text.startswith("[") or text.startswith("{"):
                try:
                    parsed = json.loads(text)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
            if parsed is not None:
                add_image(parsed)
            else:
                for separator in ("|", "，", ";", "\n", "\r"):
                    text = text.replace(separator, ",")
                for part in text.split(","):
                    add_image(part)

        unique: list[str] = []
        seen: set[str] = set()
        for image in collected:
            if image not in seen:
                unique.append(image)
                seen.add(image)
        return unique

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

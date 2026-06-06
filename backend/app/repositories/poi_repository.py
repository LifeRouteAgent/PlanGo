from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, List

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.repositories.schemas import PoiRecallConstraints, CategorySqlSpec
from app.repositories.constants import (
    CATEGORY_SQL_SPECS,
    NAME_SEARCH_LIMIT,
    RATING_FALLBACKS,
    BUDGET_FALLBACK_MULTIPLIERS,
    RADIUS_FALLBACK_MULTIPLIERS,
    SEARCH_COLLATION,
    POI_CATEGORIES,
)
from app.tools.tool_harness import ToolHarness
from app.tools.tool_policy import ToolCallRequest
from app.compat.legacy_plan_state import PoiRecord


class PoiRepository:
    """本地 MySQL POI 仓储。

    Repository 只负责“候选召回”和字段归一化；推荐打分、组合路线、方案文案仍由后续层处理。
    召回阶段会尽量在 SQL 中完成距离、评分、预算和排除词过滤，避免远/贵/明显不匹配的 POI 占满候选池。
    """

    def __init__(self, *, limit_per_category: int = 30) -> None:
        self._limit_per_category = limit_per_category

    def fetch_by_categories(
        self, categories: List[str], recall_constraints: PoiRecallConstraints | None = None
    ) -> dict[str, list[PoiRecord]]:
        """按逻辑类别批量读取 POI。

        `recall_constraints` 为空时保持兼容，仍按各表评分/热度召回；传入后启用动态 SQL 筛选。
        """

        harness = ToolHarness(
            name="database.poi.fetch_by_categories",
            timeout_seconds=8,
            max_retries=1,
            fallback=lambda *_args, **_kwargs: {category: [] for category in categories},
        )
        result = harness.run_request(
            ToolCallRequest(
                tool_name="database.poi.fetch_by_categories",
                risk_level=1,
                params={
                    "categories": categories,
                    "limit": self._limit_per_category,
                    "recall_constraints": (
                        recall_constraints.for_trace() if recall_constraints else None
                    ),
                },
            ),
            self._fetch_by_categories_once,
            categories,
            recall_constraints,
        )
        data = result.data
        return (
            data
            if result.success and isinstance(data, dict)
            else {category: [] for category in categories}
        )

    def fetch_by_name_keywords(
        self, keywords: Iterable[str], *, categories: List[str] | None = None
    ) -> dict[str, list[PoiRecord]]:
        """按用户明确点名的地点关键词检索 POI。

        must POI 召回不套动态半径，避免“我要去环球影城”这类指定地点被起点半径误杀。
        """

        keyword_list = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
        category_list = categories or list(POI_CATEGORIES)
        harness = ToolHarness(
            name="database.poi.fetch_by_name_keywords",
            timeout_seconds=8,
            max_retries=1,
            fallback=lambda *_args, **_kwargs: {category: [] for category in category_list},
        )
        result = harness.run_request(
            ToolCallRequest(
                tool_name="database.poi.fetch_by_name_keywords",
                risk_level=1,
                params={"keywords": keyword_list, "categories": category_list},
            ),
            self._fetch_by_name_keywords_once,
            keyword_list,
            category_list,
        )
        data = result.data
        return (
            data
            if result.success and isinstance(data, dict)
            else {category: [] for category in category_list}
        )

    def _fetch_by_categories_once(
        self, categories: List[str], recall_constraints: PoiRecallConstraints | None = None
    ) -> dict[str, list[PoiRecord]]:
        """执行一次真实数据库召回，外层由 ToolHarness 负责 timeout/retry/fallback。"""

        result: dict[str, list[PoiRecord]] = {}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for category in categories:
                    spec = CATEGORY_SQL_SPECS.get(category)
                    if not spec:
                        result[category] = []
                        continue
                    result[category] = self._fetch_category_with_fallback(
                        cursor, spec, recall_constraints
                    )
        return result

    def _fetch_category_with_fallback(
        self, cursor: DictCursor, spec: CategorySqlSpec, constraints: PoiRecallConstraints | None
    ) -> list[PoiRecord]:
        """按评分、预算和半径逐步放宽召回。

        放宽顺序只影响评分/预算/半径，不会移除排除词过滤；这样保证“不要火锅/不要室外”等负约束仍然生效。
        """

        target_count = max(6, self._limit_per_category)
        seen: set[str] = set()
        collected: list[PoiRecord] = []

        rating_levels = RATING_FALLBACKS if spec.rating_expr else (None,)
        budget_levels = BUDGET_FALLBACK_MULTIPLIERS if spec.price_expr else (None,)
        radius_levels = (
            RADIUS_FALLBACK_MULTIPLIERS if constraints and constraints.has_origin else (1.0,)
        )

        for radius_multiplier in radius_levels:
            for rating_threshold in rating_levels:
                for budget_multiplier in budget_levels:
                    sql, params = self._build_category_sql(
                        spec,
                        constraints,
                        rating_threshold=rating_threshold,
                        budget_multiplier=budget_multiplier,
                        radius_multiplier=radius_multiplier,
                    )
                    cursor.execute(sql, params)
                    for row in cursor.fetchall():
                        poi = self._row_to_poi(spec.category, row)
                        if not poi["id"] or poi["id"] in seen:
                            continue
                        seen.add(poi["id"])
                        collected.append(poi)
                    if len(collected) >= target_count:
                        return collected[: self._limit_per_category]
        return collected[: self._limit_per_category]

    def _fetch_by_name_keywords_once(
        self,
        keywords: Iterable[str],
        categories: List[str],
    ) -> dict[str, list[PoiRecord]]:
        """执行一次按名称关键词检索。"""

        result: dict[str, list[PoiRecord]] = {category: [] for category in categories}
        if not keywords:
            return result
        seen_ids: set[tuple[str, str]] = set()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for category in categories:
                    spec = CATEGORY_SQL_SPECS.get(category)
                    if not spec:
                        continue
                    for keyword in keywords:
                        sql, params = self._build_name_search_sql(spec, keyword)
                        cursor.execute(sql, params)
                        for row in cursor.fetchall():
                            poi = self._row_to_poi(category, row)
                            key = (category, poi["id"])
                            if key in seen_ids:
                                continue
                            seen_ids.add(key)
                            result.setdefault(category, []).append(poi)
        return result

    def table_counts(self) -> dict[str, int]:
        """读取七张 POI 表的当前行数。"""

        harness = ToolHarness(
            name="database.poi.table_counts",
            timeout_seconds=5,
            max_retries=1,
            fallback=lambda: {},
        )
        result = harness.run_request(
            ToolCallRequest(tool_name="database.poi.table_counts", risk_level=1),
            self._table_counts_once,
        )
        data = result.data
        return data if result.success and isinstance(data, dict) else {}

    def _table_counts_once(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for category, spec in CATEGORY_SQL_SPECS.items():
                    cursor.execute(f"SELECT COUNT(*) AS count_value FROM {spec.table}")
                    row = cursor.fetchone()
                    counts[category] = int(row["count_value"])
        return counts

    def _build_category_sql(
        self,
        spec: CategorySqlSpec,
        constraints: PoiRecallConstraints | None,
        *,
        rating_threshold: float | None,
        budget_multiplier: float | None,
        radius_multiplier: float,
    ) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {"limit": self._limit_per_category}
        where = [spec.base_where]
        distance_expr = self._distance_expr(spec, constraints, params)
        text_expr = self._text_expr(spec)

        if distance_expr and constraints and constraints.radius_km:
            params["radius_km"] = max(1.0, constraints.radius_km * radius_multiplier)
            where.append(f"{distance_expr} <= %(radius_km)s")

        if rating_threshold is not None and spec.rating_expr:
            params["min_rating"] = rating_threshold
            where.append(f"COALESCE(({spec.rating_expr}), 0) >= %(min_rating)s")

        max_price = self._max_price(constraints, budget_multiplier)
        if max_price is not None and spec.price_expr:
            params["max_price"] = max_price
            # 价格缺失时不直接排除，留给 Skill/Verifier 降权；有价格且明显超预算才过滤。
            where.append(
                f"(({spec.price_expr}) IS NULL OR ({spec.price_expr}) = 0 OR ({spec.price_expr}) <="
                " %(max_price)s)"
            )

        for index, term in enumerate(
            self._clean_terms(constraints.excluded_keywords if constraints else ()), start=1
        ):
            key = f"exclude_{index}"
            params[key] = f"%{term}%"
            where.append(f"{text_expr} NOT LIKE %({key})s COLLATE {SEARCH_COLLATION}")

        order_parts: list[str] = []
        preference_order = self._preference_order_expr(spec, constraints, params)
        if preference_order:
            order_parts.append(preference_order)
        if distance_expr:
            order_parts.append("distance_km ASC")
        if spec.rating_expr:
            order_parts.append(f"COALESCE(({spec.rating_expr}), 0) DESC")
        order_parts.append(spec.order_expr)

        sql = f"""
            SELECT
                {spec.id_expr} AS id,
                {spec.name_expr} AS name,
                '{spec.category}' AS category,
                {spec.subcategory_expr} AS subcategory,
                {spec.lat_expr} AS lat,
                {spec.lon_expr} AS lon,
                {spec.address_expr} AS address,
                {spec.rating_expr if spec.rating_expr else 'NULL'} AS rating,
                {spec.price_expr if spec.price_expr else 'NULL'} AS price,
                {spec.open_expr} AS open_time,
                {spec.tag_expr} AS tag_text,
                {spec.image_expr} AS image_url,
                {spec.images_expr} AS images,
                {distance_expr if distance_expr else 'NULL'} AS distance_km
            FROM {spec.table}
            WHERE {' AND '.join(where)}
            ORDER BY {', '.join(order_parts)}
            LIMIT %(limit)s
        """
        return sql, params

    def _build_name_search_sql(
        self, spec: CategorySqlSpec, keyword: str
    ) -> tuple[str, dict[str, Any]]:
        params = {
            "keyword": f"%{keyword}%",
            "exact_keyword": keyword,
            "limit": max(3, min(self._limit_per_category, NAME_SEARCH_LIMIT)),
        }
        collated_name = self._collated_expr(spec.name_expr)
        order_parts = [
            (
                f"CASE WHEN {collated_name} = %(exact_keyword)s COLLATE {SEARCH_COLLATION} THEN 0"
                " ELSE 1 END"
            ),
        ]
        if spec.rating_expr:
            order_parts.append(f"COALESCE(({spec.rating_expr}), 0) DESC")
        order_parts.append(spec.order_expr)
        sql = f"""
            SELECT
                {spec.id_expr} AS id,
                {spec.name_expr} AS name,
                '{spec.category}' AS category,
                {spec.subcategory_expr} AS subcategory,
                {spec.lat_expr} AS lat,
                {spec.lon_expr} AS lon,
                {spec.address_expr} AS address,
                {spec.rating_expr if spec.rating_expr else 'NULL'} AS rating,
                {spec.price_expr if spec.price_expr else 'NULL'} AS price,
                {spec.open_expr} AS open_time,
                {spec.tag_expr} AS tag_text,
                {spec.image_expr} AS image_url,
                {spec.images_expr} AS images,
                NULL AS distance_km
            FROM {spec.table}
            WHERE {spec.base_where}
                AND {collated_name} LIKE %(keyword)s COLLATE {SEARCH_COLLATION}
            ORDER BY {', '.join(order_parts)}
            LIMIT %(limit)s
        """
        return sql, params

    def _connect(self):
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

    def _distance_expr(
        self,
        spec: CategorySqlSpec,
        constraints: PoiRecallConstraints | None,
        params: dict[str, Any],
    ) -> str:
        if not constraints or not constraints.has_origin:
            return ""
        params["origin_lat"] = constraints.origin_lat
        params["origin_lon"] = constraints.origin_lon
        inner = (
            f"COS(RADIANS(%(origin_lat)s)) * COS(RADIANS({spec.lat_expr})) "
            f"* COS(RADIANS({spec.lon_expr}) - RADIANS(%(origin_lon)s)) "
            f"+ SIN(RADIANS(%(origin_lat)s)) * SIN(RADIANS({spec.lat_expr}))"
        )
        return f"(6371 * ACOS(LEAST(1, GREATEST(-1, {inner}))))"

    def _text_expr(self, spec: CategorySqlSpec) -> str:
        text = (
            "CONCAT_WS(' ', "
            f"COALESCE({spec.name_expr}, ''), "
            f"COALESCE({spec.subcategory_expr}, ''), "
            f"COALESCE({spec.address_expr}, ''), "
            f"COALESCE({spec.tag_expr}, '')"
            ")"
        )
        # 各 POI 表来自不同数据源，字符集/排序规则可能不一致。
        # 所有 LIKE 检索统一转成同一 collation，避免中文关键词触发 MySQL collation mismatch。
        return self._collated_expr(text)

    def _collated_expr(self, expression: str) -> str:
        return f"(CAST(({expression}) AS CHAR CHARACTER SET utf8mb4) COLLATE {SEARCH_COLLATION})"

    def _preference_order_expr(
        self,
        spec: CategorySqlSpec,
        constraints: PoiRecallConstraints | None,
        params: dict[str, Any],
    ) -> str:
        terms = self._clean_terms(constraints.preference_keywords if constraints else ())[:6]
        if not terms:
            return ""
        text_expr = self._text_expr(spec)
        likes: list[str] = []
        for index, term in enumerate(terms, start=1):
            key = f"pref_{index}"
            params[key] = f"%{term}%"
            likes.append(f"{text_expr} LIKE %({key})s COLLATE {SEARCH_COLLATION}")
        return f"CASE WHEN {' OR '.join(likes)} THEN 0 ELSE 1 END"

    def _max_price(
        self, constraints: PoiRecallConstraints | None, budget_multiplier: float | None
    ) -> float | None:
        if not constraints or budget_multiplier is None:
            return None
        per_person = constraints.per_person_budget
        if per_person is None:
            return None
        # 本地生活里预算常包含多个 slot，SQL 召回只做早期粗过滤，因此给单点价格保留一定弹性。
        return max(40.0, per_person * budget_multiplier)

    def _row_to_poi(self, category: str, row: dict[str, Any]) -> PoiRecord:
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
        distance = self._safe_float(row.get("distance_km"), default=0)
        if distance > 0:
            record["distance_km"] = round(distance, 3)
        images = self._split_images(row.get("images"))
        image_url = self._first_image(row.get("image_url")) or (images[0] if images else "")
        if image_url:
            record["image_url"] = image_url
        if images:
            record["images"] = images
        return record

    def _parse_coordinates(self, row: dict[str, Any]) -> tuple[float, float]:
        location = row.get("location")
        if location and "," in str(location):
            lat_text, lon_text = str(location).split(",", 1)
            return self._safe_float(lat_text), self._safe_float(lon_text)
        return self._safe_float(row.get("lat")), self._safe_float(row.get("lon"))

    def _split_tags(self, value: Any) -> list[str]:
        if not value:
            return []
        text = str(value)
        for separator in ("|", "，", ",", "、", ";", "；", "\n", "\r"):
            text = text.replace(separator, " ")
        return [item.strip() for item in text.split() if item.strip()]

    def _first_image(self, value: Any) -> str:
        images = self._split_images(value)
        return images[0] if images else ""

    def _split_images(self, value: Any) -> list[str]:
        """兼容 URL、JSON 数组、对象数组和分隔字符串形式的图片字段。"""

        collected: list[str] = []

        def add_image(item: Any) -> None:
            if not item:
                return
            if isinstance(item, str):
                text = item.strip().strip('"').strip("'")
                if text.startswith("http://") or text.startswith("https://"):
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
                except TypeError, ValueError, json.JSONDecodeError:
                    parsed = None
            if parsed is not None:
                add_image(parsed)
            else:
                for separator in ("|", "，", ";", "；", "\n", "\r"):
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
        price = self._safe_float(value, default=0)
        if price <= 0:
            return "unknown"
        if price < 80:
            return "low"
        if price < 200:
            return "medium"
        return "high"

    def _open_status(self, value: Any) -> str:
        return "unknown" if not value else "open"

    def _safe_float(self, value: Any, *, default: float = 0.0) -> float:
        try:
            return float(value)
        except TypeError, ValueError:
            return default

    def _clean_terms(self, terms: Iterable[str]) -> list[str]:
        cleaned: list[str] = []
        for term in terms:
            text = str(term or "").strip()
            if not text or len(text) > 30:
                continue
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


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

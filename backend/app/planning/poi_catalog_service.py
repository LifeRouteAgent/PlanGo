from __future__ import annotations

import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from app.config import settings
from app.planning.state import POILogicalTagCatalog, POITableTagInfo
from app.repositories.constants import CATEGORY_SQL_SPECS

NORMALIZED_RETURN_FIELDS = [
    "poi_id",
    "name",
    "subcategory",
    "logic_tags",
    "address",
    "lat",
    "lng",
    "rating",
    "avg_price",
]
CATEGORY_NAMES = {
    "restaurant": "餐厅美食",
    "activity": "体验活动",
    "attraction": "景点游览",
    "shopping": "购物",
    "entertainment": "休闲娱乐",
    "fitness": "运动健身",
    "beauty": "美容养生",
}
LEGACY_TO_LOGICAL = {
    "poi_restaurant": "restaurant",
    "poi_activity": "activity",
    "poi_attraction": "attraction",
    "poi_shopping": "shopping",
    "poi_entertainment": "entertainment",
    "poi_fitness": "fitness",
    "poi_beauty": "beauty",
}
FALLBACK_TAGS = {
    "restaurant": ["中餐", "火锅", "烧烤", "咖啡", "奶茶", "川菜", "北京菜", "烤鸭"],
    "activity": ["京剧", "沉浸式体验", "包车游览", "景点门票"],
    "attraction": ["历史建筑", "博物馆", "公园", "自然山水", "主题乐园", "夜游观景"],
    "shopping": ["综合商场", "服饰鞋包", "书店画廊", "运动户外", "美妆", "集市"],
    "entertainment": ["KTV", "电影院", "棋牌室", "桌游", "私人影院", "VR体验"],
    "fitness": ["健身中心", "瑜伽", "游泳馆", "搏击", "舞蹈培训", "篮球场"],
    "beauty": ["按摩", "足疗", "SPA", "美发", "美容", "美甲", "艾灸", "洗浴"],
}
SEMANTIC_ALIAS_HINTS = {
    "唱歌": {"category": "entertainment", "tags": ["KTV", "ktv", "量贩式KTV"]},
    "看电影": {"category": "entertainment", "tags": ["电影院", "cinema", "私人影院"]},
    "打麻将": {"category": "entertainment", "tags": ["棋牌室", "chess"]},
    "打牌": {"category": "entertainment", "tags": ["棋牌室", "chess"]},
    "逛街": {"category": "shopping", "tags": ["综合商场", "街区", "集市"]},
    "运动": {"category": "fitness", "tags": ["健身中心", "健身房", "运动场馆"]},
    "按摩": {"category": "beauty", "tags": ["按摩", "massage", "中医推拿", "盲人按摩"]},
    "泡澡": {"category": "beauty", "tags": ["洗浴", "bath", "洗浴中心"]},
}
TAG_SPLIT_PATTERN = re.compile(r"[|,;/，；、&]+")
PROMPT_TOP_TAGS_PER_CATEGORY = 80
CACHE_TTL_SECONDS = 1800


@dataclass
class CatalogSnapshot:
    physical_fields: dict[str, list[str]]
    tags: dict[str, list[str]]
    loaded_at: float


_cache_lock = threading.Lock()
_cache: CatalogSnapshot | None = None


class PoiCatalogService:
    """Builds a database-backed POI schema and tag catalog for planning context."""

    def load_catalog(self, *, query: str = "") -> POILogicalTagCatalog:
        snapshot = self._snapshot()
        tables: dict[str, POITableTagInfo] = {}
        for legacy_category, spec in CATEGORY_SQL_SPECS.items():
            logical = LEGACY_TO_LOGICAL[legacy_category]
            physical_fields = snapshot.physical_fields.get(spec.table, [])
            all_tags = snapshot.tags.get(logical) or FALLBACK_TAGS[logical]
            prompt_tags = self._prompt_tags(query, all_tags)
            tables[logical] = POITableTagInfo(
                physical_table=spec.table,
                logical_category=logical,
                category_name=CATEGORY_NAMES[logical],
                physical_fields=physical_fields,
                filter_fields=[field for field in spec.filter_fields if field in physical_fields],
                tag_fields=[field for field in spec.tag_fields if field in physical_fields],
                supported_logic_tags=prompt_tags,
                total_logic_tag_count=len(all_tags),
                queryable_fields=NORMALIZED_RETURN_FIELDS,
                default_sort=[spec.order_expr],
                es_search_fields=[spec.name_expr, *spec.tag_fields],
            )
        return POILogicalTagCatalog(
            tag_version=f"database-{int(snapshot.loaded_at)}",
            tables=tables,
        )

    def background_knowledge(self, catalog: POILogicalTagCatalog) -> dict[str, Any]:
        return {
            "mapping_rule": (
                "只能把用户语义映射为 available_tags 中真实存在的标签；"
                "不要编造标签。positive_logic_tags 表示偏好，negative_logic_tags 表示排除。"
            ),
            "semantic_alias_hints": SEMANTIC_ALIAS_HINTS,
            "categories": {
                category: {
                    "category_name": table.category_name,
                    "physical_table": table.physical_table,
                    "filter_fields": table.filter_fields,
                    "tag_fields": table.tag_fields,
                    "available_tags": table.supported_logic_tags,
                    "total_tag_count": table.total_logic_tag_count,
                }
                for category, table in catalog.tables.items()
            },
        }

    def match_query_tags(
        self,
        query: str,
        catalog: POILogicalTagCatalog,
    ) -> dict[str, dict[str, list[str]]]:
        """Map explicit user wording to real catalog tags without inventing labels."""

        positive_text, negative_text = self._split_negative_text(query)
        result: dict[str, dict[str, list[str]]] = {}
        for category, table in catalog.tables.items():
            available = table.supported_logic_tags
            positive = [tag for tag in available if tag.lower() in positive_text.lower()]
            negative = [tag for tag in available if tag.lower() in negative_text.lower()]
            for alias, hint in SEMANTIC_ALIAS_HINTS.items():
                if hint["category"] != category:
                    continue
                target = (
                    negative
                    if alias in negative_text
                    else positive if alias in positive_text else None
                )
                if target is None:
                    continue
                target.extend(tag for tag in available if tag in hint["tags"])
            positive = [tag for tag in dict.fromkeys(positive) if tag not in negative]
            negative = list(dict.fromkeys(negative))
            if positive or negative:
                result[category] = {"positive": positive, "negative": negative}
        positive_categories = {
            category for category, matches in result.items() if matches["positive"]
        }
        if positive_categories:
            return {
                category: matches
                for category, matches in result.items()
                if category in positive_categories
            }
        return result

    def _snapshot(self) -> CatalogSnapshot:
        global _cache
        now = time.time()
        if _cache and now - _cache.loaded_at < CACHE_TTL_SECONDS:
            return _cache
        with _cache_lock:
            if _cache and now - _cache.loaded_at < CACHE_TTL_SECONDS:
                return _cache
            try:
                _cache = self._load_from_database(now)
            except Exception:  # noqa: BLE001
                _cache = CatalogSnapshot(
                    physical_fields={
                        spec.table: list(spec.filter_fields) for spec in CATEGORY_SQL_SPECS.values()
                    },
                    tags={category: list(tags) for category, tags in FALLBACK_TAGS.items()},
                    loaded_at=now,
                )
            return _cache

    def _load_from_database(self, loaded_at: float) -> CatalogSnapshot:
        physical_fields: dict[str, list[str]] = {}
        tags: dict[str, list[str]] = {}
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for legacy_category, spec in CATEGORY_SQL_SPECS.items():
                    logical = LEGACY_TO_LOGICAL[legacy_category]
                    cursor.execute(
                        """
                        SELECT COLUMN_NAME
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
                        ORDER BY ORDINAL_POSITION
                        """,
                        (settings.database_name, spec.table),
                    )
                    columns = [str(row["COLUMN_NAME"]) for row in cursor.fetchall()]
                    physical_fields[spec.table] = columns
                    tags[logical] = self._load_tags(
                        cursor, spec.table, spec.tag_fields, set(columns)
                    )
        return CatalogSnapshot(physical_fields=physical_fields, tags=tags, loaded_at=loaded_at)

    def _load_tags(
        self,
        cursor: DictCursor,
        table: str,
        tag_fields: tuple[str, ...],
        existing_fields: set[str],
    ) -> list[str]:
        counter: Counter[str] = Counter()
        for field in tag_fields:
            if field not in existing_fields:
                continue
            cursor.execute(f"""
                SELECT CAST(`{field}` AS CHAR) AS tag_value, COUNT(*) AS tag_count
                FROM `{table}`
                WHERE `{field}` IS NOT NULL AND TRIM(CAST(`{field}` AS CHAR)) <> ''
                GROUP BY `{field}`
                """)
            for row in cursor.fetchall():
                count = int(row.get("tag_count") or 0)
                for tag in self._split_tags(row.get("tag_value")):
                    counter[tag] += count
        return [tag for tag, _ in counter.most_common()]

    def _prompt_tags(self, query: str, all_tags: list[str]) -> list[str]:
        selected = list(all_tags[:PROMPT_TOP_TAGS_PER_CATEGORY])
        lowered = query.lower()
        matched = [
            tag
            for tag in all_tags
            if tag.lower() in lowered or (len(query) >= 2 and lowered in tag.lower())
        ]
        for alias, hint in SEMANTIC_ALIAS_HINTS.items():
            if alias not in query:
                continue
            matched.extend(tag for tag in all_tags if tag in hint["tags"])
        return list(dict.fromkeys([*matched, *selected]))

    def _split_tags(self, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        tags = []
        for item in TAG_SPLIT_PATTERN.split(str(value)):
            tag = item.strip()
            if 1 < len(tag) <= 24 and tag not in tags:
                tags.append(tag)
        return tags

    def _split_negative_text(self, query: str) -> tuple[str, str]:
        negative_markers = ("不要", "不想", "排除", "避开", "别去", "不去")
        positive_parts: list[str] = []
        negative_parts: list[str] = []
        for clause in re.split(r"[，。；;,.]+", query):
            if any(marker in clause for marker in negative_markers):
                negative_parts.append(clause)
            else:
                positive_parts.append(clause)
        return " ".join(positive_parts), " ".join(negative_parts)

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

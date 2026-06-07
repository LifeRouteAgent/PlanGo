from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.planning.state import POILogicalTagCatalog, POITableTagInfo
from app.repositories.poi_repository import CATEGORY_SQL_SPECS
from app.planning.poi_tag_background import (
    load_static_poi_tag_background,
    static_tag_fields_by_table,
    static_tags_by_logical_category,
)
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
STATIC_TAGS = static_tags_by_logical_category()
STATIC_TAG_FIELDS = static_tag_fields_by_table()
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
PROMPT_TOP_TAGS_PER_CATEGORY = 80


@dataclass
class CatalogSnapshot:
    physical_fields: dict[str, list[str]]
    tags: dict[str, list[str]]
    tag_version: str


class PoiCatalogService:
    """构建给 LLM 使用的 POI 标签背景知识。

    这里不访问数据库。标签变化不频繁，由 `poi_tag_background.json` 维护；
    物理表和字段白名单来自 `CATEGORY_SQL_SPECS`，用于告诉 LLM 后续可匹配哪些字段。
    真正的 POI 数据库查询只发生在召回阶段的 PoiRepository。
    """

    def load_catalog(self, *, query: str = "") -> POILogicalTagCatalog:
        snapshot = self._snapshot()
        tables: dict[str, POITableTagInfo] = {}
        for legacy_category, spec in CATEGORY_SQL_SPECS.items():
            logical = LEGACY_TO_LOGICAL[legacy_category]
            physical_fields = snapshot.physical_fields.get(spec.table, [])
            # LLM 可选标签只来自静态背景和短 fallback，不在 intent 阶段扫描数据库。
            all_tags = _merge_tag_lists(
                snapshot.tags.get(logical),
                FALLBACK_TAGS[logical],
            )
            prompt_tags = self._prompt_tags(query, all_tags)
            tag_fields = _merge_field_lists(
                [field for field in spec.tag_fields if field in physical_fields],
                [field for field in STATIC_TAG_FIELDS.get(spec.table, []) if field in physical_fields],
            )
            tables[logical] = POITableTagInfo(
                physical_table=spec.table,
                logical_category=logical,
                category_name=CATEGORY_NAMES[logical],
                physical_fields=physical_fields,
                filter_fields=[field for field in spec.filter_fields if field in physical_fields],
                tag_fields=tag_fields,
                supported_logic_tags=prompt_tags,
                total_logic_tag_count=len(all_tags),
                queryable_fields=NORMALIZED_RETURN_FIELDS,
                default_sort=[spec.order_expr],
                es_search_fields=[spec.name_expr, *spec.tag_fields],
            )
        return POILogicalTagCatalog(
            tag_version=snapshot.tag_version,
            tables=tables,
        )

    def background_knowledge(self, catalog: POILogicalTagCatalog) -> dict[str, Any]:
        static_background = load_static_poi_tag_background()
        return {
            "mapping_rule": (
                "只能把用户语义映射为 available_tags 中真实存在的标签；"
                "不要编造标签。available_tags 来自静态 POI 标签背景知识，不在 LLM 阶段查询数据库。"
                "positive_logic_tags 表示偏好，后续用于 SQL LIKE 排序加分和候选打分；"
                "negative_logic_tags 表示排除，后续用于 SQL NOT LIKE 过滤。"
            ),
            "tag_source": {
                "database_tags": "not_used_for_intent_background",
                "static_tags": "source_of_truth_for_llm_available_tags",
                "static_background_version": static_background.get("version", ""),
                "split_separators": static_background.get("split_separators", []),
                "ignored_tables": static_background.get("ignored_tables", {}),
            },
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
        static_background = load_static_poi_tag_background()
        return CatalogSnapshot(
            physical_fields={
                spec.table: _merge_field_lists(
                    spec.filter_fields,
                    spec.tag_fields,
                    STATIC_TAG_FIELDS.get(spec.table),
                )
                for spec in CATEGORY_SQL_SPECS.values()
            },
            tags={
                category: _merge_tag_lists(STATIC_TAGS.get(category), fallback_tags)
                for category, fallback_tags in FALLBACK_TAGS.items()
            },
            tag_version=str(static_background.get("version") or "static-poi-tags"),
        )

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


def _merge_tag_lists(*groups: list[str] | tuple[str, ...] | None) -> list[str]:
    """合并标签列表并保序去重。

    数据库标签通常最新，静态背景更完整，短 fallback 只在前两者缺失时兜底。
    """

    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            tag = str(item).strip()
            if not tag or tag in seen:
                continue
            seen.add(tag)
            merged.append(tag)
    return merged


def _merge_field_lists(*groups: list[str] | tuple[str, ...] | None) -> list[str]:
    """合并物理标签字段，避免同一字段重复出现在 prompt 背景里。"""

    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            field = str(item).strip()
            if not field or field in seen:
                continue
            seen.add(field)
            merged.append(field)
    return merged

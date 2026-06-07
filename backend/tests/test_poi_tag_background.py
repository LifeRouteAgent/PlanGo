from __future__ import annotations

from app.planning.poi_catalog_service import PoiCatalogService
from app.planning.poi_tag_background import (
    load_static_poi_tag_background,
    static_tag_fields_by_table,
    static_tags_by_logical_category,
)


def test_static_poi_tag_background_splits_compound_labels() -> None:
    """用户提供的复合标签应拆成可独立匹配的 LLM 白名单标签。"""

    data = load_static_poi_tag_background()
    shopping_tags = {
        item["name"]
        for item in data["tables"]["poi_shoppings"]["tags"]
        if isinstance(item, dict)
    }

    assert {"二手店", "市场", "食品", "时装"}.issubset(shopping_tags)
    assert "二手店/市场|食品|时装" not in shopping_tags


def test_static_background_keeps_table_tag_fields() -> None:
    """背景知识要保留每张表真实标签字段，供 prompt 和召回白名单使用。"""

    fields = static_tag_fields_by_table()

    assert fields["poi_attractions"] == ["tags"]
    assert fields["poi_entertainment"] == ["keytag"]
    assert fields["poi_fitness"] == ["fitness_tag"]
    assert fields["poi_restaurant"] == ["cuisine_tag"]


def test_catalog_uses_static_tags_as_llm_source_of_truth() -> None:
    """LLM 意图识别阶段只使用静态标签背景，不为了标签目录查询数据库。"""

    catalog = PoiCatalogService().load_catalog(query="想逛二手店和食品市场，再吃火锅")
    knowledge = PoiCatalogService().background_knowledge(catalog)

    shopping_tags = knowledge["categories"]["shopping"]["available_tags"]
    restaurant_total = knowledge["categories"]["restaurant"]["total_tag_count"]

    assert "二手店" in shopping_tags
    assert "食品" in shopping_tags
    assert restaurant_total > 9000
    assert knowledge["tag_source"]["database_tags"] == "not_used_for_intent_background"
    assert knowledge["tag_source"]["static_background_version"] == "provided-tags-2026-06-07"
    assert knowledge["tag_source"]["static_tags"] == "source_of_truth_for_llm_available_tags"


def test_static_tags_are_grouped_by_logical_category() -> None:
    """静态标签最终按 planning 使用的逻辑类别组织，而不是按物理表名裸用。"""

    tags = static_tags_by_logical_category()

    assert "shopping" in tags
    assert "restaurant" in tags
    assert "食品" in tags["shopping"]
    assert "火锅" in tags["restaurant"]

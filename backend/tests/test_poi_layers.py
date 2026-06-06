from __future__ import annotations

from app.graph.services import build_constraints, compile_recall_plan, resolve_intent
from app.graph.state import POILogicalTagCatalog, POITableTagInfo


def test_poi_recall_compiler_uses_whitelisted_repository_tables() -> None:
    understanding = resolve_intent("推荐几个适合朋友聚会的餐厅", {}, {})
    constraints, recall = build_constraints(understanding, city="北京", origin=None)

    catalog = POILogicalTagCatalog(
        tables={
            "restaurant": POITableTagInfo(
                physical_table="poi_restaurant",
                logical_category="restaurant",
                category_name="餐厅",
                physical_fields=["id", "name", "rating"],
                filter_fields=["rating"],
                tag_fields=["cuisine_tag"],
                queryable_fields=["poi_id", "name", "rating"],
                default_sort=["rating DESC"],
            )
        }
    )

    compiled = compile_recall_plan(recall, constraints, catalog)

    assert compiled.queries
    assert {query.physical_table for query in compiled.queries} <= {"poi_restaurant"}
    assert all("*" not in query.safe_return_fields for query in compiled.queries)

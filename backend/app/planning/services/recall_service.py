from __future__ import annotations

from app.planning.services.common import *


def compile_recall_plan(
    logical: LogicalRecallPlan, constraints: FinalConstraints, catalog: Any
) -> CompiledRecallPlan:
    queries: list[CompiledRecallQuery] = []
    for requirement in logical.slot_recall_requirements:
        for category in requirement.logical_categories:
            if category not in PHYSICAL_TABLES or category not in catalog.tables:
                raise ValueError(f"unsupported logical_category: {category}")
            table = catalog.tables[category]
            limit = min(500, max(300, requirement.limit))
            queries.append(
                CompiledRecallQuery(
                    query_id=f"{requirement.slot_id}:{category}",
                    slot_id=requirement.slot_id,
                    logical_category=category,
                    physical_table=table.physical_table,
                    safe_return_fields=list(table.queryable_fields),
                    filters={
                        "radius_km": constraints.distance_policy.initial_radius_km,
                        "min_rating": constraints.rating_policy.min_rating_initial,
                        "avoid_keywords": constraints.hard_constraints.avoid_keywords,
                        "positive_logic_tags": requirement.positive_logic_tags,
                        "negative_logic_tags": requirement.negative_logic_tags,
                        "filter_fields": table.filter_fields,
                        "tag_fields": table.tag_fields,
                    },
                    es_name_match=ESNameMatchPlan(
                        enabled=bool(logical.keyword_recall.preference_keywords),
                        should_keywords=logical.keyword_recall.preference_keywords,
                        avoid_keywords=logical.keyword_recall.avoid_keywords,
                    ),
                    sort=list(table.default_sort),
                    limit=limit,
                )
            )
    return CompiledRecallPlan(
        queries=queries,
        must_poi_resolution=MustPOIResolutionPlan(
            enabled=bool(logical.keyword_recall.must_keywords),
            keywords=logical.keyword_recall.must_keywords,
        ),
    )


def collect_candidates(
    compiled: CompiledRecallPlan, constraints: FinalConstraints
) -> tuple[dict[str, list[SafePOICandidate]], RecallStats]:
    origin = constraints.hard_constraints.origin
    legacy_categories = list(
        dict.fromkeys(f"poi_{query.logical_category}" for query in compiled.queries)
    )
    name_repository = PoiRepository(limit_per_category=80)
    must = (
        name_repository.fetch_by_name_keywords(
            compiled.must_poi_resolution.keywords, categories=legacy_categories
        )
        if compiled.must_poi_resolution.enabled
        else {}
    )
    must_found = any(items for items in must.values())
    hard_must_added = False
    result: dict[str, list[SafePOICandidate]] = {}
    stats: list[QueryRecallStat] = []
    for query in compiled.queries:
        legacy = f"poi_{query.logical_category}"
        repository = PoiRepository(limit_per_category=query.limit)
        recall_constraints = PoiRecallConstraints(
            origin_lat=origin.lat if origin else None,
            origin_lon=origin.lng if origin else None,
            radius_km=constraints.distance_policy.initial_radius_km,
            budget=constraints.budget_policy.total_budget,
            people_count=1,
            scene_type="v2",
            duration_hours=(constraints.time_policy.duration_minutes or 270) / 60,
            preference_keywords=tuple(
                _dedupe([
                    *constraints.soft_preferences.preference_keywords,
                    *query.filters.get("positive_logic_tags", []),
                ])
            ),
            excluded_keywords=tuple(
                _dedupe([
                    *constraints.hard_constraints.avoid_keywords,
                    *query.filters.get("negative_logic_tags", []),
                ])
            ),
        )
        rows = repository.fetch_by_categories([legacy], recall_constraints=recall_constraints)
        items = [*_safe_candidates(rows.get(legacy, []), query, False)]
        name_matches = _safe_candidates(must.get(legacy, []), query, False)
        if compiled.must_poi_resolution.enabled and not hard_must_added:
            if name_matches:
                anchor = name_matches[0].model_copy(
                    update={"must_include": True, "recall_source": "must_keyword"}
                )
                items.append(anchor)
                items.extend(name_matches[1:])
                hard_must_added = True
            elif not must_found:
                items.append(
                    _synthetic_must_candidate(compiled.must_poi_resolution.keywords[0], query)
                )
                hard_must_added = True
        else:
            items.extend(name_matches)
        items = list({item.poi_id: item for item in items}.values())
        result.setdefault(query.slot_id, []).extend(items)
        stats.append(
            QueryRecallStat(
                query_id=query.query_id, raw_count=len(items), after_hard_filter_count=len(items)
            )
        )
    total = sum(len(items) for items in result.values())
    return result, RecallStats(
        by_query=stats, total_raw_count=total, total_after_filter_count=total
    )


def _safe_candidates(
    rows: list[dict[str, Any]], query: CompiledRecallQuery, must: bool
) -> list[SafePOICandidate]:
    return [
        SafePOICandidate(
            poi_id=str(row.get("id")),
            name=str(row.get("name")),
            logical_category=query.logical_category,
            physical_table=query.physical_table,
            subcategory=row.get("subcategory"),
            logic_tags=_clean_logic_tags(
                row.get("tags", []), query.logical_category, row.get("subcategory")
            ),
            address=row.get("address"),
            lat=row.get("lat"),
            lng=row.get("lon"),
            distance_km=row.get("distance_km"),
            rating=row.get("rating"),
            avg_price=row.get("avg_price"),
            image_url=_first_image_value(row.get("image_url"), row.get("images")),
            images=_image_list(row.get("images"), row.get("image_url")),
            recall_source="must_keyword" if must else "dynamic_sql",
            must_include=must,
            raw_extra={
                key: row.get(key)
                for key in ("open_status", "price_level")
                if row.get(key) is not None
            },
        )
        for row in rows
    ]


def _synthetic_must_candidate(name: str, query: CompiledRecallQuery) -> SafePOICandidate:
    safe_name = str(name or "用户指定地点").strip()[:80] or "用户指定地点"
    return SafePOICandidate(
        poi_id=f"user_must:{abs(hash((query.slot_id, safe_name))) % 10_000_000}",
        name=safe_name,
        logical_category=query.logical_category,
        physical_table=query.physical_table,
        subcategory=query.logical_category,
        logic_tags=["用户指定", "必去"],
        address="用户指定地点，数据库暂无详情",
        lat=None,
        lng=None,
        distance_km=None,
        rating=4.0,
        avg_price=None,
        recall_source="user_must_fallback",
        fallback_level=0,
        must_include=True,
        raw_extra={"open_status": "unknown"},
    )

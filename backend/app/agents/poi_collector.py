from __future__ import annotations

from typing import Any

from pymysql import MySQLError

from app.config import settings
from app.services.poi_repository import PoiRecallConstraints, PoiRepository
from app.state.plan_state import PlanState, PlanStatePatch
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


def poi_collector_node(state: PlanState) -> PlanStatePatch:
    """统一 POI Collector 节点。

    Collector 只负责候选召回和统一字段归一化；个性化推荐、路线组合和验证仍交给后续节点。
    """

    categories = state.get("dag_plan", {}).get("collector_categories") or []
    if state.get("force_empty_candidates") and state.get("replanning_count", 0) <= 1:
        return {
            "candidate_pois": {category: [] for category in categories},
            "logs": ["POI Collector: forced empty candidates for branch verification"],
        }

    use_database = settings.use_database
    if use_database:
        try:
            repository = PoiRepository()
            constraints = state.get("constraints", {})
            recall_constraints = _build_recall_constraints(state)
            candidate_pois = repository.fetch_by_categories(
                categories,
                recall_constraints=recall_constraints,
            )
            preference_pois = repository.fetch_by_name_keywords(
                constraints.get("preference_keywords", []),
                categories=categories or None,
            )
            must_pois = repository.fetch_by_name_keywords(
                constraints.get("must_keywords", []),
                categories=categories or None,
            )
            must_pois = _select_best_must_pois(must_pois, constraints)
            candidate_pois = _merge_preference_pois(candidate_pois, preference_pois)
            candidate_pois = _merge_must_pois(candidate_pois, must_pois, constraints)
            candidate_pois = _filter_candidates(candidate_pois, constraints)
            total = sum(len(items) for items in candidate_pois.values())
            must_total = sum(len(items) for items in must_pois.values())
            return {
                "candidate_pois": candidate_pois,
                "constraints": {
                    **constraints,
                    "must_pois": _flatten_must_pois(must_pois),
                },
                "tool_evidence": [
                    {
                        "tool_name": "poi_repository.fetch_by_categories",
                        "source": "mysql",
                        "summary": {
                            "categories": categories,
                            "candidate_count": total,
                            "must_poi_count": must_total,
                            "recall_constraints": recall_constraints.for_trace(),
                        },
                        "confidence": 0.86,
                    }
                ],
                "logs": [
                    f"POI Collector: loaded {total} candidates from MySQL database"
                    + (f", must_pois={must_total}" if constraints.get("must_keywords") else "")
                ],
            }
        except MySQLError as exc:
            return {
                "candidate_pois": _filter_candidates(
                    {category: _mock_pois(category) for category in categories},
                    state.get("constraints", {}),
                ),
                "tool_evidence": [
                    {
                        "tool_name": "poi_repository.fetch_by_categories",
                        "source": "mock_fallback",
                        "summary": {"categories": categories, "error": str(exc)},
                        "confidence": 0.35,
                        "fallback_used": True,
                    }
                ],
                "logs": [f"POI Collector: database unavailable, fallback to mock: {exc}"],
            }

    candidate_pois = _filter_candidates(
        {category: _mock_pois(category) for category in categories},
        state.get("constraints", {}),
    )
    return {
        "candidate_pois": candidate_pois,
        "tool_evidence": [
            {
                "tool_name": "poi_repository.fetch_by_categories",
                "source": "mock",
                "summary": {
                    "categories": categories,
                    "candidate_count": sum(len(items) for items in candidate_pois.values()),
                },
                "confidence": 0.4,
                "fallback_used": True,
            }
        ],
        "logs": [f"POI Collector: collected mock candidates for {len(categories)} categories"],
    }


def _build_recall_constraints(state: PlanState) -> PoiRecallConstraints:
    """把 PlanState 转成数据库候选召回阶段使用的轻量约束。

    优先使用 LLM/Planner 结构化字段；只有字段缺失时，才用原始 query 做轻量兜底。
    """

    constraints = state.get("constraints", {}) or {}
    dag_plan = state.get("dag_plan", {}) or {}
    user_profile = state.get("user_profile", {}) or {}
    origin_lat, origin_lon = _extract_origin(constraints, user_profile)
    people_count = _safe_int(
        constraints.get("people_count") or user_profile.get("people_count") or 1,
        default=1,
    )
    duration_hours = _safe_float(constraints.get("duration_hours"), default=None)
    movement_policy = str(
        dag_plan.get("movement_policy")
        or constraints.get("movement_policy")
        or "balanced_local"
    )
    candidate_strategy = str(dag_plan.get("candidate_strategy") or "")
    scene_type = str(constraints.get("scenario") or constraints.get("scene_type") or "unknown")
    radius_km = _dynamic_radius_km(
        state=state,
        constraints=constraints,
        scene_type=scene_type,
        duration_hours=duration_hours,
        movement_policy=movement_policy,
        candidate_strategy=candidate_strategy,
    )
    return PoiRecallConstraints(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        radius_km=radius_km,
        budget=_safe_float(constraints.get("budget"), default=None),
        people_count=max(1, people_count),
        scene_type=scene_type,
        duration_hours=duration_hours,
        movement_policy=movement_policy,
        candidate_strategy=candidate_strategy,
        preference_keywords=tuple(_recall_preference_terms(constraints)),
        excluded_keywords=tuple(_recall_excluded_terms(constraints)),
    )


def _extract_origin(constraints: dict[str, Any], user_profile: dict[str, Any]) -> tuple[float | None, float | None]:
    """从约束和用户画像中提取召回起点；缺失时用北京中心点兜底。"""

    origin_candidates = [
        constraints.get("origin"),
        constraints.get("start_location"),
        user_profile.get("origin"),
        user_profile.get("start_location"),
        user_profile.get("home"),
    ]
    common_origins = user_profile.get("common_origins")
    if isinstance(common_origins, list) and common_origins:
        origin_candidates.append(common_origins[0])
    for origin in origin_candidates:
        lat, lon = _lat_lon_from_value(origin)
        if lat is not None and lon is not None:
            return lat, lon

    lat = _safe_float(
        constraints.get("origin_lat")
        or constraints.get("start_lat")
        or user_profile.get("origin_lat")
        or user_profile.get("start_lat"),
        default=None,
    )
    lon = _safe_float(
        constraints.get("origin_lon")
        or constraints.get("origin_lng")
        or constraints.get("start_lon")
        or constraints.get("start_lng")
        or user_profile.get("origin_lon")
        or user_profile.get("origin_lng")
        or user_profile.get("start_lon")
        or user_profile.get("start_lng"),
        default=None,
    )
    if lat is not None and lon is not None:
        return lat, lon
    return 39.9042, 116.4074


def _lat_lon_from_value(value: object) -> tuple[float | None, float | None]:
    if not isinstance(value, dict):
        return None, None
    lat = _safe_float(value.get("lat") or value.get("latitude"), default=None)
    lon = _safe_float(value.get("lon") or value.get("lng") or value.get("longitude"), default=None)
    return lat, lon


def _dynamic_radius_km(
    *,
    state: PlanState,
    constraints: dict[str, Any],
    scene_type: str,
    duration_hours: float | None,
    movement_policy: str,
    candidate_strategy: str,
) -> float:
    """根据结构化规划约束生成数据库召回半径。"""

    duration = duration_hours or 6.0
    if duration <= 2.5:
        radius = 5.0
    elif duration <= 4:
        radius = 8.0
    elif duration <= 6:
        radius = 12.0
    else:
        radius = 18.0

    lower_scene = scene_type.lower()
    policy_text = f"{movement_policy} {candidate_strategy}".lower()
    if any(token in lower_scene for token in ("family", "parent", "child", "亲子", "家庭")):
        radius = min(radius, 8.0)
    if any(token in policy_text for token in ("same_area", "same_business_area", "compact", "low_movement", "nearby")):
        radius = min(radius, 8.0)
    if any(token in policy_text for token in ("broaden", "popular", "landmark", "scenic", "far_ok")):
        radius = max(radius, 18.0)

    max_route = _safe_float(constraints.get("max_route_minutes"), default=None)
    route_source = str(constraints.get("max_route_minutes_source") or "")
    if max_route is not None and route_source not in {"default", "system"} and max_route <= 45:
        radius = min(radius, 8.0)

    distance_preference = str(constraints.get("distance_preference") or "").lower()
    if distance_preference in {"nearby", "close", "low_movement"}:
        radius = min(radius, 6.0)
    elif distance_preference in {"far_ok", "popular_first", "worth_travel"}:
        radius = max(radius, 20.0)

    # 规则只做兜底：结构化字段未表达远近偏好时，才从原始 query 做轻量判断。
    query = str(state.get("user_query") or "")
    has_structured_distance = bool(distance_preference) or any(
        token in policy_text for token in ("nearby", "far_ok", "popular")
    )
    if not has_structured_distance:
        if _contains_any(query, ("别太远", "附近", "家附近", "不想跑太远", "近一点")):
            radius = min(radius, 6.0)
        elif _contains_any(query, ("可以远一点", "值得去", "热门景点", "远一点也行")):
            radius = max(radius, 20.0)
    return round(max(3.0, min(radius, 30.0)), 1)


def _recall_preference_terms(constraints: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    terms.extend(_as_str_list(constraints.get("preference_keywords")))
    terms.extend(_as_str_list(constraints.get("must_keywords")))
    for intent in constraints.get("activity_intents") or []:
        if isinstance(intent, dict):
            terms.extend(_as_str_list(intent.get("keywords")))
            for key in ("semantic_type", "category", "name"):
                value = str(intent.get(key) or "").strip()
                if value:
                    terms.append(value)
        else:
            value = str(intent or "").strip()
            if value:
                terms.append(value)
    return _dedupe_terms(terms)


def _recall_excluded_terms(constraints: dict[str, Any]) -> list[str]:
    return _dedupe_terms([
        *_as_str_list(constraints.get("avoid_tags")),
        *_as_str_list(constraints.get("excluded_keywords")),
        *_as_str_list(constraints.get("must_not_pois")),
    ])


def _mock_pois(category: str) -> list[dict[str, Any]]:
    """数据库不可用时的最小 mock 候选。"""

    samples = {
        POI_ATTRACTION: ("城市公园", "park", ["亲子", "散步", "低强度"]),
        POI_ACTIVITY: ("周末手作体验", "workshop", ["朋友", "体验", "可预约"]),
        POI_RESTAURANT: ("邻里轻食餐厅", "light_food", ["低脂", "适合聊天"]),
        POI_SHOPPING: ("社区生活广场", "mall", ["购物", "室内"]),
        POI_FITNESS: ("轻运动健身馆", "fitness", ["运动", "室内"]),
        POI_ENTERTAINMENT: ("小型影院", "cinema", ["电影", "休闲"]),
        POI_BEAUTY: ("放松按摩馆", "massage", ["养生", "按摩"]),
    }
    name, subcategory, tags = samples.get(category, ("本地生活点位", "general", ["本地"]))
    return [
        make_poi_record(
            id=f"{category}_mock_1",
            name=name,
            category=category,
            subcategory=subcategory,
            lat=39.9042,
            lon=116.4074,
            address="北京市示例商圈",
            rating=4.6,
            price_level="medium",
            open_status="open",
            tags=tags,
        )
    ]


def _filter_candidates(
    candidate_pois: dict[str, list[dict[str, Any]]],
    constraints: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """按本轮负向约束过滤候选 POI，作为 SQL 过滤后的二次兜底。"""

    avoid_terms = _recall_excluded_terms(constraints)
    if not avoid_terms:
        return candidate_pois

    filtered: dict[str, list[dict[str, Any]]] = {}
    for category, items in candidate_pois.items():
        kept = []
        for item in items:
            text = " ".join([
                str(item.get("name", "")),
                str(item.get("subcategory", "")),
                str(item.get("address", "")),
                " ".join(str(tag) for tag in item.get("tags", [])),
            ])
            if any(term in text for term in avoid_terms):
                continue
            kept.append(item)
        filtered[category] = kept
    return filtered


def _merge_must_pois(
    candidate_pois: dict[str, list[dict[str, Any]]],
    must_pois: dict[str, list[dict[str, Any]]],
    constraints: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """把明确点名地点合并到候选池前部，并打上 must_include 标记。"""

    must_keywords = [str(keyword) for keyword in constraints.get("must_keywords", [])]
    merged = {category: list(items) for category, items in candidate_pois.items()}
    for category, items in must_pois.items():
        bucket = merged.setdefault(category, [])
        seen = {str(item.get("id")) for item in bucket}
        for item in items:
            marked_item = {
                **item,
                "must_include": True,
                "must_keyword": _matched_keyword(item, must_keywords),
            }
            if str(marked_item.get("id")) in seen:
                for index, existing in enumerate(bucket):
                    if str(existing.get("id")) == str(marked_item.get("id")):
                        bucket[index] = {**existing, **marked_item}
                        break
                continue
            bucket.insert(0, marked_item)
            seen.add(str(marked_item.get("id")))
    return merged


def _merge_preference_pois(
    candidate_pois: dict[str, list[dict[str, Any]]],
    preference_pois: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """把偏好关键词召回结果合并到候选池前部。"""

    merged = {category: list(items) for category, items in candidate_pois.items()}
    for category, items in preference_pois.items():
        bucket = merged.setdefault(category, [])
        seen = {str(item.get("id")) for item in bucket}
        insert_at = 0
        for item in items:
            item_id = str(item.get("id"))
            if item_id in seen:
                continue
            bucket.insert(insert_at, {**item, "preference_keyword_match": True})
            insert_at += 1
            seen.add(item_id)
    return merged


def _select_best_must_pois(
    must_pois: dict[str, list[dict[str, Any]]],
    constraints: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """从名称召回结果中挑选真正需要强制进入候选池的地点。"""

    must_keywords = [str(keyword) for keyword in constraints.get("must_keywords", []) if str(keyword).strip()]
    all_items = [item for items in must_pois.values() for item in items]
    universal = [
        item
        for item in all_items
        if "环球" in str(item.get("name", "")) and "度假" in str(item.get("name", ""))
    ]
    if universal:
        best = sorted(universal, key=lambda item: -float(item.get("rating", 0) or 0))[0]
        return {str(best.get("category")): [best]}

    selected: dict[str, list[dict[str, Any]]] = {}
    for category, items in must_pois.items():
        if not items:
            selected[category] = []
            continue
        sorted_items = sorted(
            items,
            key=lambda item: (
                0 if _matched_keyword(item, must_keywords) else 1,
                -float(item.get("rating", 0) or 0),
            ),
        )
        selected[category] = sorted_items[:1]
    return selected


def _matched_keyword(item: dict[str, Any], keywords: list[str]) -> str:
    text = " ".join([
        str(item.get("name", "")),
        str(item.get("address", "")),
        str(item.get("subcategory", "")),
        " ".join(str(tag) for tag in item.get("tags", [])),
    ])
    for keyword in keywords:
        if keyword and keyword in text:
            return keyword
    return ""


def _flatten_must_pois(must_pois: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for items in must_pois.values():
        for item in items:
            result.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "category": item.get("category"),
                    "lat": item.get("lat"),
                    "lon": item.get("lon"),
                    "address": item.get("address"),
                    "must_keyword": item.get("must_keyword", ""),
                }
            )
    return result


def _as_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _dedupe_terms(terms: list[str]) -> list[str]:
    result: list[str] = []
    for term in terms:
        text = str(term or "").strip()
        if not text or len(text) > 30:
            continue
        if text not in result:
            result.append(text)
    return result


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _safe_float(value: object, *, default: float | None = 0.0) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default

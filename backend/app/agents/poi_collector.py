from __future__ import annotations

from pymysql import MySQLError

from app.config import settings
from app.services.poi_repository import PoiRepository
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

    当前 Gate 3 只返回 mock 数据，不读取也不迁移 `Hackathon/data` 下的高德文件。
    后续接入真实数据时，保持本节点输出字段不变即可。
    """

    categories = state.get("dag_plan", {}).get("collector_categories") or []
    if state.get("force_empty_candidates") and state.get("replanning_count", 0) <= 1:
        return {
            "candidate_pois": {category: [] for category in categories},
            "logs": ["POI Collector: forced empty candidates for branch verification"],
        }

    # 本项目已经进入本地数据库驱动阶段，数据源只由 backend/.env 控制。
    # 不再允许 user_profile.use_database 覆盖配置，避免一次请求把系统降级到 mock 数据。
    use_database = settings.use_database
    if use_database:
        try:
            repository = PoiRepository()
            constraints = state.get("constraints", {})
            candidate_pois = repository.fetch_by_categories(categories)
            preference_pois = repository.fetch_by_name_keywords(
                constraints.get("preference_keywords", []),
                categories=categories or None,
            )
            must_pois = repository.fetch_by_name_keywords(
                constraints.get("must_keywords", []),
                categories=categories or None,
            )
            must_pois = _select_best_must_pois(must_pois)
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
                "tool_evidence": [{
                    "tool_name": "poi_repository.fetch_by_categories",
                    "source": "mysql",
                    "summary": {
                        "categories": categories,
                        "candidate_count": total,
                        "must_poi_count": must_total,
                    },
                    "confidence": 0.86,
                }],
                "logs": [
                    f"POI Collector: loaded {total} candidates from MySQL database"
                    + (f", must_pois={must_total}" if constraints.get("must_keywords") else "")
                ],
            }
        except MySQLError as exc:
            # 数据库不可用时降级到 mock，保证 DAG 本身仍可运行；错误细节进入 logs 供排查。
            return {
                "candidate_pois": _filter_candidates(
                    {category: _mock_pois(category) for category in categories},
                    state.get("constraints", {}),
                ),
                "tool_evidence": [{
                    "tool_name": "poi_repository.fetch_by_categories",
                    "source": "mock_fallback",
                    "summary": {"categories": categories, "error": str(exc)},
                    "confidence": 0.35,
                    "fallback_used": True,
                }],
                "logs": [f"POI Collector: database unavailable, fallback to mock: {exc}"],
            }

    candidate_pois = _filter_candidates(
        {category: _mock_pois(category) for category in categories},
        state.get("constraints", {}),
    )

    return {
        "candidate_pois": candidate_pois,
        "tool_evidence": [{
            "tool_name": "poi_repository.fetch_by_categories",
            "source": "mock",
            "summary": {
                "categories": categories,
                "candidate_count": sum(len(items) for items in candidate_pois.values()),
            },
            "confidence": 0.4,
            "fallback_used": True,
        }],
        "logs": [f"POI Collector: collected mock candidates for {len(categories)} categories"],
    }


def _mock_pois(category: str) -> list[dict]:
    """为指定逻辑表生成一条统一 POI mock 记录。"""

    samples = {
        POI_ATTRACTION: ("城市公园", "park", ["亲子", "散步", "低强度"]),
        POI_ACTIVITY: ("周末手作体验", "workshop", ["朋友", "体验", "可预约"]),
        POI_RESTAURANT: ("邻里轻食餐厅", "light_food", ["低脂", "可订位", "适合聊天"]),
        POI_SHOPPING: ("社区生活广场", "mall", ["购物", "室内"]),
        POI_FITNESS: ("轻运动健身馆", "fitness", ["运动", "室内"]),
        POI_ENTERTAINMENT: ("小型影城", "cinema", ["电影", "休闲"]),
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
    candidate_pois: dict[str, list[dict]],
    constraints: dict,
) -> dict[str, list[dict]]:
    """按本轮修正约束过滤候选 POI。

    例如用户中途说“不要室外了，今天太热”，会写入 avoid_tags/excluded_keywords，
    Collector 在源头过滤明显不合适的候选，后续 Skill 和 Route Planner 就不会继续消耗它们。
    """

    avoid_terms = [
        str(term)
        for term in [
            *constraints.get("avoid_tags", []),
            *constraints.get("excluded_keywords", []),
        ]
        if str(term).strip()
    ]
    if not avoid_terms:
        return candidate_pois

    filtered: dict[str, list[dict]] = {}
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
    candidate_pois: dict[str, list[dict]],
    must_pois: dict[str, list[dict]],
    constraints: dict,
) -> dict[str, list[dict]]:
    """把明确点名地点合并到普通候选池，并打上 must_include 标记。"""

    must_keywords = [str(keyword) for keyword in constraints.get("must_keywords", [])]
    merged = {category: list(items) for category, items in candidate_pois.items()}
    for category, items in must_pois.items():
        bucket = merged.setdefault(category, [])
        seen = {str(item.get("id")) for item in bucket}
        for item in items:
            item = {
                **item,
                "must_include": True,
                "must_keyword": _matched_keyword(item, must_keywords),
            }
            if str(item.get("id")) in seen:
                for index, existing in enumerate(bucket):
                    if str(existing.get("id")) == str(item.get("id")):
                        bucket[index] = {**existing, **item}
                        break
                continue
            bucket.insert(0, item)
            seen.add(str(item.get("id")))
    return merged


def _merge_preference_pois(
    candidate_pois: dict[str, list[dict]],
    preference_pois: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    """把偏好关键词召回的 POI 合并到候选池。

    这类 POI 只表示“更符合用户想唱歌/打牌/看电影的方向”，不代表必须进入方案。
    插入到候选池前部可以让 Skill 和 Route Planner 更容易生成不同地点备选。
    """

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


def _select_best_must_pois(must_pois: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """从名称召回结果里选真正要强制包含的地点。

    名称 LIKE 可能召回“环球影城店”这类周边商家。v1 先按 exact/高评分做保守选择：
    如果存在“北京环球度假区”，只强制它一个；否则每个类别最多保留一个最相关结果。
    """

    all_items = [item for items in must_pois.values() for item in items]
    universal = [
        item
        for item in all_items
        if str(item.get("name")) in {"北京环球度假区", "北京环球城市大道"}
    ]
    if universal:
        best = sorted(
            universal,
            key=lambda item: (
                0 if str(item.get("name")) == "北京环球度假区" else 1,
                -float(item.get("rating", 0) or 0),
            ),
        )[0]
        return {str(best.get("category")): [best]}

    selected: dict[str, list[dict]] = {}
    for category, items in must_pois.items():
        if not items:
            selected[category] = []
            continue
        selected[category] = [
            sorted(
                items,
                key=lambda item: (
                    0 if "店" not in str(item.get("name", "")) else 1,
                    -float(item.get("rating", 0) or 0),
                ),
            )[0]
        ]
    return selected


def _flatten_must_pois(must_pois: dict[str, list[dict]]) -> list[dict]:
    """压缩 must POI 信息，写回 constraints 供 Trace、Response 和调试面板展示。"""

    result: list[dict] = []
    for items in must_pois.values():
        for item in items:
            result.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "lat": item.get("lat"),
                "lon": item.get("lon"),
                "address": item.get("address"),
            })
    return result


def _matched_keyword(item: dict, keywords: list[str]) -> str:
    text = str(item.get("name", ""))
    for keyword in keywords:
        if keyword in text or text in keyword:
            return keyword
    return keywords[0] if keywords else ""

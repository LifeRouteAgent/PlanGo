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
            candidate_pois = _filter_candidates(
                PoiRepository().fetch_by_categories(categories),
                state.get("constraints", {}),
            )
            total = sum(len(items) for items in candidate_pois.values())
            return {
                "candidate_pois": candidate_pois,
                "logs": [f"POI Collector: loaded {total} candidates from MySQL database"],
            }
        except MySQLError as exc:
            # 数据库不可用时降级到 mock，保证 DAG 本身仍可运行；错误细节进入 logs 供排查。
            return {
                "candidate_pois": _filter_candidates(
                    {category: _mock_pois(category) for category in categories},
                    state.get("constraints", {}),
                ),
                "logs": [f"POI Collector: database unavailable, fallback to mock: {exc}"],
            }

    candidate_pois = _filter_candidates(
        {category: _mock_pois(category) for category in categories},
        state.get("constraints", {}),
    )

    return {
        "candidate_pois": candidate_pois,
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

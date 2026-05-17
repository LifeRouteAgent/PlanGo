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

    # `user_profile.use_database=false` 用于测试和离线开发；默认跟随 backend/.env。
    use_database = state.get("user_profile", {}).get("use_database", settings.use_database)
    if use_database:
        try:
            candidate_pois = PoiRepository().fetch_by_categories(categories)
            total = sum(len(items) for items in candidate_pois.values())
            return {
                "candidate_pois": candidate_pois,
                "logs": [
                    f"POI Collector: loaded {total} candidates from MySQL database"
                ],
            }
        except MySQLError as exc:
            # 数据库不可用时降级到 mock，保证 DAG 本身仍可运行；错误细节进入 logs 供排查。
            return {
                "candidate_pois": {category: _mock_pois(category) for category in categories},
                "logs": [f"POI Collector: database unavailable, fallback to mock: {exc}"],
            }

    candidate_pois = {category: _mock_pois(category) for category in categories}

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

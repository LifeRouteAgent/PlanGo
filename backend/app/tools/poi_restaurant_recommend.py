from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import POI_RESTAURANT, recommend_poi


def poi_restaurant_recommend_node(state: PlanState) -> PlanStatePatch:
    """餐厅美食推荐 Skill。

    当前只做 mock 打分。后续真实接入时，这里会加入排队、可订位、口味、
    人均预算和儿童友好等餐饮专属因素。
    """

    items = [
        recommend_poi(
            item,
            score_boost=0.3,
            reason="餐厅推荐：符合预算与聚餐场景，优先选择可订位候选",
        )
        for item in state.get("candidate_pois", {}).get(POI_RESTAURANT, [])
    ]
    return {
        "recommended_pois": {"restaurant": items},
        "logs": [f"Skill poi_restaurant_recommend: recommended {len(items)} POIs"],
    }

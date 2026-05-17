from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import POI_ACTIVITY, recommend_poi


def poi_activity_recommend_node(state: PlanState) -> PlanStatePatch:
    """活动票券/体验推荐 Skill。

    该节点只处理活动类 POI，不关心餐厅、路线和最终时间线。
    """

    items = [
        recommend_poi(
            item,
            score_boost=0.2,
            reason="活动推荐：适合多人互动或短时体验",
        )
        for item in state.get("candidate_pois", {}).get(POI_ACTIVITY, [])
    ]
    return {
        "recommended_pois": {"activity": items},
        "logs": [f"Skill poi_activity_recommend: recommended {len(items)} POIs"],
    }

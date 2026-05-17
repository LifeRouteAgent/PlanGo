from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import (
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    recommend_poi,
)


def poi_lifestyle_recommend_node(state: PlanState) -> PlanStatePatch:
    """生活方式推荐 Skill。

    覆盖健身、娱乐、按摩美容等非餐饮类本地生活场景。
    """

    categories = (POI_FITNESS, POI_ENTERTAINMENT, POI_BEAUTY)
    items: list[dict] = []
    for category in categories:
        for item in state.get("candidate_pois", {}).get(category, []):
            items.append(
                recommend_poi(
                    item,
                    score_boost=0.15,
                    reason="生活方式推荐：适合作为餐前或餐后的轻量体验",
                )
            )
    return {
        "recommended_pois": {"lifestyle": items},
        "logs": [f"Skill poi_lifestyle_recommend: recommended {len(items)} POIs"],
    }

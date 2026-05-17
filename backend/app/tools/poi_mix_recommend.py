from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import POI_ATTRACTION, POI_SHOPPING, recommend_poi


def poi_mix_recommend_node(state: PlanState) -> PlanStatePatch:
    """景点 + 购物综合推荐 Skill。

    该 Skill 面向“先逛一逛、再补充轻活动”的需求，后续会接入用户偏好、
    天气、步行强度和商圈聚合逻辑。
    """

    categories = (POI_ATTRACTION, POI_SHOPPING)
    items = _score_items(state, categories)
    return {
        "recommended_pois": {"mix": items},
        "logs": [f"Skill poi_mix_recommend: recommended {len(items)} POIs"],
    }


def _score_items(state: PlanState, categories: tuple[str, ...]) -> list[dict]:
    """从多个 Collector 类别中挑选并打分。"""

    result: list[dict] = []
    for category in categories:
        for item in state.get("candidate_pois", {}).get(category, []):
            result.append(
                recommend_poi(
                    item,
                    score_boost=0.1,
                    reason="综合推荐：适合作为周末行程里的低压力过渡点",
                )
            )
    return result

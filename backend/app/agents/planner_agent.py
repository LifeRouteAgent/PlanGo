from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch
from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
)


def planner_agent_node(state: PlanState) -> PlanStatePatch:
    """主控 Planner Agent 节点。

    当前阶段它只根据偏好决定 Collector 需要拉取哪些 POI 逻辑表。
    后续会扩展为真正的任务拆解和 DAG 节点配置生成器。
    """

    constraints = state.get("constraints", {})
    preferences = constraints.get("preferences") or ["活动", "餐厅", "休闲娱乐"]
    categories = _categories_for_preferences(preferences)
    replanning_count = state.get("replanning_count", 0) + 1
    last_errors = set(state.get("errors", []))

    # Verifier 回退后，Planner 会收紧部分约束，避免重复生成同样失败的候选方案。
    # 这里先实现可观察的最小策略：路线超时则降低路线阈值压力；总时长超出则减少活动组合强度。
    retry_policy = "initial_plan"
    if replanning_count > 1:
        if "candidate_empty" in last_errors:
            retry_policy = "broaden_categories"
            categories = sorted(set(categories) | {POI_SHOPPING, POI_ENTERTAINMENT})
        elif "restaurant_unavailable" in last_errors:
            retry_policy = "prefer_non_restaurant_backup"
        elif "route_timeout" in last_errors or "total_duration_exceeded" in last_errors:
            retry_policy = "compact_timeline"

    return {
        "dag_plan": {
            "collector_categories": categories,
            "parallel_skills": [
                "poi_mix_recommend",
                "poi_activity_recommend",
                "poi_restaurant_recommend",
                "poi_lifestyle_recommend",
            ],
            "feedback_policy": "verifier_failed_then_replan",
            "retry_policy": retry_policy,
        },
        "replanning_count": replanning_count,
        # 每次重新规划都开启一个新的尝试轮次，清空上一轮的失败结果。
        # Planner 已经在上方读取了旧 errors 并转成 retry_policy，因此这里可以安全清空。
        "errors": [],
        "candidate_plans": [],
        "verified_plans": [],
        "routes": [],
        "logs": [
            f"Planner Agent: planned categories={','.join(categories)}, retry_policy={retry_policy}"
        ],
    }


def _categories_for_preferences(preferences: list[str]) -> list[str]:
    """根据用户偏好选择七张 POI 表中的必要类别。"""

    categories = {POI_ATTRACTION, POI_ACTIVITY, POI_RESTAURANT}
    if any(item in preferences for item in ("休闲娱乐", "健身", "美容养生", "购物")):
        categories.update(
            {
                POI_SHOPPING,
                POI_FITNESS,
                POI_ENTERTAINMENT,
                POI_BEAUTY,
            }
        )
    return sorted(categories)

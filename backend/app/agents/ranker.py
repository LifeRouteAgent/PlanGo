from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch


def ranker_node(state: PlanState) -> PlanStatePatch:
    """候选方案排序节点。

    先按 POI 数量完整度排序，再按预算和路线耗时排序。真实版本会加入用户偏好、
    距离、天气、评分、排队风险等综合因子。
    """

    ranked = sorted(
        state.get("verified_plans", []),
        key=lambda plan: (
            -len(plan.get("items", [])),
            plan.get("estimated_budget", 0),
            plan.get("route_minutes", 0),
        ),
    )
    selected = ranked[0] if ranked else {}
    return {
        "ranked_plans": ranked,
        "selected_plan": selected,
        "logs": [f"Ranker: ranked {len(ranked)} plans"],
    }

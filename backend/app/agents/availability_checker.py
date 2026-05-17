from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch


def availability_checker_node(state: PlanState) -> PlanStatePatch:
    """可用性检查节点。

    目前检查 POI 是否营业，并提供“餐厅无位”的强制测试分支。
    真实系统中这里会接餐厅排队、票务库存、预约时段和商户营业状态。
    """

    issues: list[str] = []
    for plan in state.get("candidate_plans", []):
        for item in plan.get("items", []):
            # `unknown` 代表数据库没有营业时间字段，不能直接判定为不可执行。
            # 只有明确 closed 的候选才进入错误分支。
            if item.get("open_status") == "closed":
                issues.append(f"poi_closed:{item.get('id')}")
            if (
                item.get("category") == "poi_restaurant"
                and state.get("force_restaurant_unavailable")
                and state.get("replanning_count", 0) <= 1
            ):
                issues.append("restaurant_unavailable")

    if issues:
        return {"errors": issues, "logs": ["Availability Checker: found unavailable POIs"]}
    return {"logs": ["Availability Checker: all mock POIs are available"]}

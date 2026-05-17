from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch


def verifier_node(state: PlanState) -> PlanStatePatch:
    """校验候选方案是否可执行。

    本节点只负责判断方案质量，不负责改写方案。若失败，条件边会回退 Planner。
    """

    upstream_errors = _dedupe_errors(state.get("errors", []))
    constraints = state.get("constraints", {})
    max_route_minutes = int(constraints.get("max_route_minutes", 45))
    duration_limit = int(constraints.get("duration_hours", 6)) * 60
    budget = int(constraints.get("budget", 600))
    verified: list[dict] = []
    current_errors: list[str] = []

    for plan in state.get("candidate_plans", []):
        if plan.get("route_minutes", 0) > max_route_minutes:
            current_errors.append("route_timeout")
            continue
        if plan.get("total_duration_minutes", 0) > duration_limit:
            current_errors.append("total_duration_exceeded")
            continue
        if plan.get("estimated_budget", 0) > budget:
            current_errors.append("budget_exceeded")
            continue
        verified.append({**plan, "verified": True})

    if not state.get("candidate_plans"):
        current_errors.append("candidate_empty")

    all_errors = _dedupe_errors([*upstream_errors, *current_errors])

    return {
        "verified_plans": verified,
        "errors": all_errors,
        "logs": [
            f"Verifier: verified={len(verified)}, errors={','.join(all_errors) if all_errors else 'none'}"
        ],
    }


def verifier_route(state: PlanState) -> str:
    """根据 Verifier 结果选择下一条 DAG 边。"""

    has_verified = bool(state.get("verified_plans"))
    has_errors = bool(state.get("errors"))
    can_replan = state.get("replanning_count", 0) < state.get("max_replanning_count", 1)
    if has_verified and not has_errors:
        return "rank"
    if has_errors and can_replan:
        return "replan"
    return "respond"


def _dedupe_errors(errors: list[str]) -> list[str]:
    """保持错误出现顺序的去重工具，避免反馈循环产生重复错误。"""

    seen: set[str] = set()
    result: list[str] = []
    for error in errors:
        if error not in seen:
            seen.add(error)
            result.append(error)
    return result

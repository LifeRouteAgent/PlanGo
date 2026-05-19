from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.issue_utils import (
    dedupe_issues,
    format_issue_codes,
    has_blocking_issue,
    make_issue,
    normalize_issues,
)
from app.state.plan_state import PlanState, PlanStatePatch


def verifier_node(state: PlanState) -> PlanStatePatch:
    """校验候选方案是否可执行。

    Gate 5 开始，Verifier 不再只返回字符串错误，而是返回结构化问题对象：
    `code/message/suggestion/severity/source/details`。

    校验分两层：
    - error：阻断执行，会触发 Planner 回退或最终失败响应。
    - warning：不阻断执行，但会挂到方案上，供 Ranker 降权和前端展示。
    """

    upstream_issues = normalize_issues(state.get("errors", []))
    constraints = state.get("constraints", {})
    max_route_minutes = int(constraints.get("max_route_minutes", 45))
    duration_limit = int(float(constraints.get("duration_hours", 6))) * 60
    budget = int(float(constraints.get("budget", 600)))
    verified: list[dict[str, Any]] = []
    current_issues: list[dict[str, Any]] = []

    candidate_plans = state.get("candidate_plans", [])
    if not candidate_plans:
        current_issues.append(make_issue("candidate_empty", source="verifier"))

    for plan in candidate_plans:
        plan_issues = _issues_for_plan(plan, max_route_minutes, duration_limit, budget)
        blocking = [issue for issue in plan_issues if issue.get("severity") == "error"]
        if blocking:
            current_issues.extend(blocking)
            continue
        # 可执行方案保留 warning，后续 Ranker 会根据 warning 降权。
        verified.append({**plan, "verified": True, "issues": plan_issues})
        current_issues.extend(issue for issue in plan_issues if issue.get("severity") == "warning")

    all_issues = dedupe_issues([*upstream_issues, *current_issues])
    # 如果已经有可执行方案，则不让 warning 阻断 DAG；真正阻断的是 error 级问题。
    if verified:
        upstream_blocking = [issue for issue in upstream_issues if issue.get("severity") == "error"]
        warnings = [issue for issue in all_issues if issue.get("severity") == "warning"]
        all_issues = dedupe_issues([*upstream_blocking, *warnings])

    return {
        "verified_plans": verified,
        "errors": all_issues,
        "logs": [f"Verifier: verified={len(verified)}, issues={format_issue_codes(all_issues)}"],
    }


def verifier_route(state: PlanState) -> str:
    """根据 Verifier 结果选择下一条 DAG 边。"""

    has_verified = bool(state.get("verified_plans"))
    has_blocking = has_blocking_issue(state.get("errors", []))
    can_replan = state.get("replanning_count", 0) < state.get("max_replanning_count", 1)
    if has_verified and not has_blocking:
        return "rank"
    if has_blocking and can_replan:
        return "replan"
    return "respond"


def _issues_for_plan(
    plan: dict[str, Any],
    max_route_minutes: int,
    duration_limit: int,
    budget: int,
) -> list[dict[str, Any]]:
    """对单个候选方案执行完整可行性校验。"""

    issues: list[dict[str, Any]] = []
    route_minutes = int(plan.get("route_minutes", 0))
    total_duration = int(plan.get("total_duration_minutes", 0))
    estimated_budget = int(plan.get("estimated_budget", 0))

    if route_minutes > max_route_minutes:
        issues.append(
            make_issue(
                "route_timeout",
                source="verifier",
                details={
                    "plan_id": plan.get("id"),
                    "route_minutes": route_minutes,
                    "max_route_minutes": max_route_minutes,
                },
            )
        )
    if total_duration > duration_limit:
        issues.append(
            make_issue(
                "total_duration_exceeded",
                source="verifier",
                details={
                    "plan_id": plan.get("id"),
                    "total_duration_minutes": total_duration,
                    "duration_limit": duration_limit,
                },
            )
        )
    if estimated_budget > budget:
        issues.append(
            make_issue(
                "budget_exceeded",
                source="verifier",
                details={
                    "plan_id": plan.get("id"),
                    "estimated_budget": estimated_budget,
                    "budget": budget,
                },
            )
        )

    issues.extend(_category_duplication_issues(plan))
    issues.extend(_route_segment_issues(plan))
    issues.extend(_item_risk_issues(plan))
    return dedupe_issues(issues)


def _category_duplication_issues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """检查同类 POI 是否重复过多。"""

    category_counts = Counter(item.get("category") for item in plan.get("items", []))
    duplicated = [category for category, count in category_counts.items() if count >= 2]
    if not duplicated:
        return []
    return [
        make_issue(
            "duplicate_category",
            source="verifier",
            details={"plan_id": plan.get("id"), "categories": duplicated},
        )
    ]


def _route_segment_issues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """检查跨区移动和单段交通过长。"""

    issues: list[dict[str, Any]] = []
    for segment in plan.get("route_segments", []):
        distance_km = float(segment.get("distance_km", 0) or 0)
        duration_minutes = int(segment.get("duration_minutes", 0) or 0)
        if distance_km >= 15 or segment.get("transport_mode") == "cross_district_taxi":
            issues.append(
                make_issue(
                    "cross_district_move",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "from": segment.get("from"),
                        "to": segment.get("to"),
                        "distance_km": distance_km,
                    },
                )
            )
        if duration_minutes > 45:
            issues.append(
                make_issue(
                    "route_timeout",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "from": segment.get("from"),
                        "to": segment.get("to"),
                        "duration_minutes": duration_minutes,
                    },
                )
            )
    return issues


def _item_risk_issues(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """把 Skill 输出的风险信号转成方案级 warning/error。"""

    issues: list[dict[str, Any]] = []
    for item in plan.get("items", []):
        if item.get("open_status") == "closed":
            issues.append(
                make_issue(
                    "poi_closed",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "poi_id": item.get("id"),
                        "poi_name": item.get("name"),
                    },
                )
            )
        if item.get("crowd_risk") == "high" or "queue_risk" in item.get("risk_flags", []):
            issues.append(
                make_issue(
                    "queue_risk",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "poi_id": item.get("id"),
                        "poi_name": item.get("name"),
                    },
                )
            )
        if item.get("reservation_required") or "reservation_required" in item.get("risk_flags", []):
            issues.append(
                make_issue(
                    "reservation_required",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "poi_id": item.get("id"),
                        "poi_name": item.get("name"),
                    },
                )
            )
        if "open_time_unknown" in item.get("risk_flags", []):
            issues.append(
                make_issue(
                    "open_time_unknown",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "poi_id": item.get("id"),
                        "poi_name": item.get("name"),
                    },
                )
            )
        if "weak_preference_match" in item.get("risk_flags", []):
            issues.append(
                make_issue(
                    "weak_preference_match",
                    source="verifier",
                    details={
                        "plan_id": plan.get("id"),
                        "poi_id": item.get("id"),
                        "poi_name": item.get("name"),
                    },
                )
            )
    return issues

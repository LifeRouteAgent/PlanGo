from __future__ import annotations

import json
from typing import Any

from app.agents.issue_utils import dedupe_issues, make_issue, normalize_issues
from app.services.context_builder import ContextBuilder
from app.services.llm_service import call_chat_completion, extract_json_object
from app.services.llm_output_schemas import CriticOutput, validate_llm_output
from app.services.trace_recorder import record_trace_event
from app.state.plan_state import PlanState, PlanStatePatch

ALLOWED_CODES = {
    "pace_risk",
    "scene_mismatch",
    "weak_preference_match",
    "alternative_too_similar",
    "timeline_inconsistent",
    "explanation_mismatch",
}

ALLOWED_SEVERITIES = {"info", "warning", "error"}


def llm_critic_node(state: PlanState) -> PlanStatePatch:
    """LLM Critic / QA 节点。

    Rule Verifier 负责预算、路线、时长、空候选等确定性校验；这个节点只判断
    方案节奏、同行关系、偏好冲突、备选差异度等软性合理性。LLM 不允许新增 POI、
    价格、路线或营业信息，只能基于 `verified_plans` 输出结构化 issue。
    """

    verified_plans = [dict(plan) for plan in state.get("verified_plans", [])]
    if not verified_plans:
        return {"logs": ["LLM Critic: skipped because there are no verified plans"]}
    context_snapshot = ContextBuilder().build_for("llm_critic", state)

    raw = call_chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是本地生活行程方案 Critic。只能审查输入 JSON 中已有方案。"
                    "禁止新增地点、价格、路线、天气、营业状态。"
                    "只输出 JSON 对象，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context_snapshot": context_snapshot,
                        "plans": [_compact_plan(plan) for plan in verified_plans[:3]],
                        "required_schema": {
                            "issues": [{
                                "code": "pace_risk | scene_mismatch | weak_preference_match | alternative_too_similar | timeline_inconsistent | explanation_mismatch",
                                "severity": "info | warning | error",
                                "message": "问题描述，必须基于输入事实",
                                "suggestion": "改进建议，不能新增地点",
                                "target_plan_id": "输入里的 plan id，可为空",
                                "target_item_id": "输入里的 item id，可为空",
                                "confidence": 0.0,
                            }]
                        },
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        temperature=0.15,
        timeout_seconds=25,
        max_completion_tokens=1200,
        prompt_name="llm_critic",
        schema_name="CriticOutput",
    )
    parsed = extract_json_object(raw)
    validation = (
        validate_llm_output(CriticOutput, parsed, source="llm_critic")
        if isinstance(parsed, dict)
        else None
    )
    critic_issues = _sanitize_issues(validation.data, verified_plans) if validation and validation.ok else []
    updated_plans = _attach_plan_issues(verified_plans, critic_issues)
    record_trace_event(
        "llm_critic",
        {
            "success": bool(parsed),
            "schema_valid": bool(validation and validation.ok),
            "raw_preview": raw[:600] if raw else "",
            "issues": critic_issues,
        },
    )
    return {
        "verified_plans": updated_plans,
        "errors": dedupe_issues([*state.get("errors", []), *critic_issues]),
        "logs": [
            "LLM Critic: "
            + (
                f"generated {len(critic_issues)} structured issues"
                if parsed
                else "LLM unavailable, skipped soft QA"
            )
        ],
    }


def _safe_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    """给 LLM Critic 的约束摘要，移除完整 LLM 原始缓存。"""

    return {
        key: value
        for key, value in constraints.items()
        if key not in {"llm_understanding"}
    }


def _compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """压缩方案，只保留 Critic 需要审查的事实。"""

    return {
        "id": plan.get("id") or plan.get("plan_id"),
        "title": plan.get("title"),
        "plan_score": plan.get("plan_score"),
        "estimated_budget": plan.get("estimated_budget"),
        "total_duration_minutes": plan.get("total_duration_minutes"),
        "route_minutes": plan.get("route_minutes"),
        "fit_summary": plan.get("fit_summary"),
        "items": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "category": item.get("category"),
                "subcategory": item.get("subcategory"),
                "rating": item.get("rating"),
                "reason": item.get("reason"),
                "tags": item.get("tags", [])[:5],
                "risk_flags": item.get("risk_flags", []),
            }
            for item in plan.get("items", [])
        ],
        "timeline": plan.get("timeline", []),
        "route_segments": plan.get("route_segments", []),
        "issues": normalize_issues(plan.get("issues", [])),
    }


def _sanitize_issues(
    parsed: dict[str, Any],
    plans: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把 LLM 输出清洗成标准 issue。"""

    raw_issues = parsed.get("issues")
    if not isinstance(raw_issues, list):
        return []
    plan_ids = {str(plan.get("id") or plan.get("plan_id")) for plan in plans}
    item_ids = {
        str(item.get("id"))
        for plan in plans
        for item in plan.get("items", [])
        if item.get("id") is not None
    }
    issues: list[dict[str, Any]] = []
    for item in raw_issues[:12]:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if code not in ALLOWED_CODES:
            code = "weak_preference_match"
        severity = str(item.get("severity") or "warning").strip()
        if severity not in ALLOWED_SEVERITIES:
            severity = "warning"
        target_plan_id = str(item.get("target_plan_id") or "")
        target_item_id = str(item.get("target_item_id") or "")
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        issues.append(
            make_issue(
                code,
                severity=severity,
                message=str(item.get("message") or "LLM Critic 发现软性合理性风险。"),
                suggestion=str(item.get("suggestion") or "建议调整方案节奏或偏好匹配。"),
                source="llm_critic",
                target_plan_id=target_plan_id if target_plan_id in plan_ids else "",
                target_item_id=target_item_id if target_item_id in item_ids else "",
                details={"confidence": confidence},
            )
        )
    return dedupe_issues(issues)


def _attach_plan_issues(
    plans: list[dict[str, Any]],
    critic_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把有 target_plan_id 的 Critic issue 挂回对应方案。"""

    issues_by_plan: dict[str, list[dict[str, Any]]] = {}
    for issue in critic_issues:
        plan_id = str(issue.get("target_plan_id") or "")
        if not plan_id:
            continue
        issues_by_plan.setdefault(plan_id, []).append(issue)

    updated: list[dict[str, Any]] = []
    for plan in plans:
        plan_id = str(plan.get("id") or plan.get("plan_id") or "")
        updated.append({
            **plan,
            "issues": dedupe_issues([*plan.get("issues", []), *issues_by_plan.get(plan_id, [])]),
        })
    return updated

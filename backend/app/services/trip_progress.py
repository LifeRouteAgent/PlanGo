from __future__ import annotations

from typing import Any

NODE_PRESENTATION = {
    "request_context_loader": ("准备请求", "正在整理位置和请求信息。"),
    "session_state_loader": ("读取会话", "正在读取上一轮方案和会话摘要。"),
    "memory_reader": ("读取偏好", "正在读取长期偏好。"),
    "intent_resolver": ("理解需求", "正在判断请求类型和场景。"),
    "async_event_emitter": ("记录任务", "已记录本次规划任务。"),
    "request_router": ("选择流程", "已选择合适的规划流程。"),
    "constraint_builder": ("整理条件", "已整理时间、预算、位置和移动范围。"),
    "planner": ("生成策略", "已确定活动槽位和规划策略。"),
    "plan_editor": ("调整方案", "已确定本轮需要替换和保留的部分。"),
    "recall_plan_compiler": ("准备检索", "已生成安全地点检索计划。"),
    "collector": ("检索地点", "正在从本地数据库筛选候选地点。"),
    "poi_scorer": ("地点评分", "已完成地点评分。"),
    "candidate_pool_balancer": ("平衡候选", "已保留更多样的候选地点。"),
    "route_planner": ("生成动线", "已组合带路线和时间线的候选方案。"),
    "availability_checker": ("可用性检查", "正在检查地点营业和预约风险。"),
    "verifier": ("校验可执行性", "正在检查时间、预算和路线。"),
    "optional_critic": ("体验检查", "已完成方案体验风险检查。"),
    "ranker": ("方案排序", "已按整体体验对方案排序。"),
    "single_category_ranker": ("推荐排序", "已完成地点推荐排序。"),
    "response_assembler": ("整理结果", "正在整理前端可展示的方案信息。"),
    "response_generator": ("生成回答", "正在生成最终说明。"),
    "simple_response_generator": ("生成回答", "已生成回答。"),
    "session_state_saver": ("保存会话", "已保存本轮结果。"),
    "post_skill_router": ("推荐汇总", "已汇总各类地点推荐结果。"),
    "poi_lifestyle_recommend": ("生活方式 Skill", "已完成生活方式地点排序。"),
    "poi_restaurant_recommend": ("餐厅推荐 Skill", "已完成餐厅地点排序。"),
    "user_confirm": ("方案确认", "已完成方案确认。"),
    "execution_agent": ("执行准备", "已完成模拟执行准备。"),
}


def build_agent_thinking_payload(
    node_name: str,
    patch: dict[str, Any] | None = None,
    current_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del patch, current_state
    title, message = NODE_PRESENTATION.get(node_name, ("规划处理中", "正在继续处理本次请求。"))
    return {"agent": node_name, "title": title, "message": message, "summary": {}}


def trace_events_for_node(
    node_name: str,
    patch: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
) -> list[tuple[str, dict[str, Any]]]:
    del patch
    state = current_state or {}
    if node_name in {"intent_router", "intent_resolver"}:
        return [("intent_detected", {
            "stage": "understanding", "title": "理解需求", "message": "已识别请求类型和目标类别。",
            "intent_type": state.get("intent_type", ""), "answer_mode": state.get("answer_mode", ""),
            "target_categories": _safe_list(state.get("target_categories")),
        })]
    if node_name in {"planner_agent", "planner"}:
        plan = state.get("dag_plan") or state.get("planning_strategy") or {}
        return [("skill_selected", {
            "stage": "planning", "title": "选择规划策略", "message": "已确定规划策略和活动槽位。",
            "planning_template": plan.get("planning_template", ""),
            "enabled_skills": _safe_list(plan.get("enabled_skills")),
            "collector_categories": _safe_list(plan.get("collector_categories")),
            "slot_sequence": _safe_list(plan.get("slot_sequence") or plan.get("required_slots")),
            "movement_policy": plan.get("movement_policy", ""), "candidate_strategy": plan.get("candidate_strategy", ""),
        })]
    if node_name in {"route_time_planner", "route_planner"}:
        plans = state.get("candidate_plans") or []
        first = plans[0] if plans and isinstance(plans[0], dict) else {}
        return [("route_candidate_built", {
            "stage": "routing", "title": "生成动线", "message": f"已组合 {len(plans)} 个带时间线的候选方案。",
            "candidate_plan_count": len(plans), "best_duration_minutes": first.get("total_duration_minutes"),
            "best_route_minutes": first.get("route_minutes"), "best_budget": first.get("estimated_budget"),
        })]
    if node_name == "verifier":
        issues = _public_issues(state.get("errors", []))
        return [("verification_issue", {
            "stage": "checking", "title": "校验可执行性", "message": "已完成方案可执行性校验。",
            "verified_count": len(state.get("verified_plans") or []), "issue_count": len(issues), "issues": issues,
        })]
    if node_name == "ranker":
        plans = state.get("ranked_plans") or []
        first = plans[0] if plans and isinstance(plans[0], dict) else {}
        return [("plan_ranked", {
            "stage": "ranking_plans", "title": "方案排序", "message": f"已综合排序出 {len(plans)} 个方案。",
            "ranked_count": len(plans), "selected_plan_id": first.get("id") or first.get("plan_id"),
            "top_plan_score": first.get("plan_score"),
        })]
    return []


def effective_query_for_request(saved_session: dict[str, Any] | None, current_query: str) -> str:
    if not isinstance(saved_session, dict):
        return current_query
    latest = saved_session.get("latest_state")
    response = saved_session.get("latest_response")
    if not isinstance(latest, dict):
        return current_query
    waiting = bool(latest.get("need_clarification")) or (
        isinstance(response, dict) and bool(response.get("need_clarification"))
    )
    previous = str(latest.get("user_query") or "").strip()
    reply = current_query.strip()
    return f"{previous}\n补充信息：{reply}" if waiting and previous and reply else current_query


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _public_issues(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {
            key: issue.get(key)
            for key in ("code", "severity", "message", "suggestion", "source", "target_plan_id", "target_item_id")
            if issue.get(key) is not None
        }
        for issue in value[:8]
        if isinstance(issue, dict)
    ]

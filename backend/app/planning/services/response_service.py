from __future__ import annotations

from app.planning.payloads import normalize_response_payload
from app.planning.services.common import *
from app.planning.services.ranking_service import _candidate_index
from app.planning.services.routing_service import _route_segments_for_items
from app.planning.state import (
    CandidatePlan,
    OriginPoint,
    PlanSlot,
    RankedPlan,
    ScoredPOICandidate,
)


def assemble_state_response(state: Any) -> dict[str, Any]:
    """把内部 PlanningState 转成前端 payload。

    这里是业务结果到展示契约的边界：只读取已经排序好的方案和候选索引，
    不在响应阶段重新计算路线、召回候选或改变方案顺序。
    """

    request_type = (
        state.llm_understanding.intent.request_type
        if state.llm_understanding
        else "full_itinerary_plan"
    )
    item_index = _candidate_index(state.candidates.scored_candidates)
    ranked_by_id = {ranked.plan_id: ranked for ranked in state.plans.ranked_plans}
    ordered = [
        plan
        for plan in state.plans.candidate_plans
        if not ranked_by_id or plan.plan_id in ranked_by_id
    ]
    if ranked_by_id:
        order = {ranked.plan_id: ranked.rank for ranked in state.plans.ranked_plans}
        ordered.sort(key=lambda plan: order.get(plan.plan_id, 999))
    cards = [
        _state_plan_card(plan, ranked_by_id.get(plan.plan_id), item_index, state)
        for plan in ordered[:3]
    ]
    failure_reason = state.debug.recall_debug.get("failure_reason")
    payload = {
        "response_type": (
            "plan_adjustment_result" if request_type == "plan_adjustment" else "plan_cards"
        ),
        "summary": "已生成可用方案。" if cards else "暂时没有足够可用方案。",
        "plans": cards,
        "selected_plan": cards[0] if cards else {},
        "failure_reason": failure_reason,
        "preference_context": _preference_context_payload(state),
        "warnings": (
            [f"方案不足原因：{failure_reason}"] if failure_reason and len(cards) < 3 else []
        ),
        "followup_suggestions": (
            ["换一批地点", "放宽距离", "调整预算"] if cards else ["放宽距离或预算"]
        ),
    }
    return normalize_response_payload(payload)


def _preference_context_payload(state: Any) -> dict[str, Any]:
    session = state.context.session_preference_profile
    memory = state.context.user_preference_profile
    similar_profiles = [
        {
            "cluster_id": cluster.cluster_id,
            "core_tags": cluster.core_tags,
            "similarity_score": cluster.similarity_score,
        }
        for cluster in memory.positive_clusters[:3]
    ]
    return {
        "priority": [
            "current_hard_constraints",
            "current_soft_preferences",
            "long_term_memory",
            "similar_user_preferences",
            "default_popularity",
        ],
        "session_profile": session.model_dump(mode="json"),
        "long_term_tags": [tag.tag_name for tag in memory.positive_tags[:12]],
        "negative_memory_tags": [tag.tag_name for tag in memory.negative_tags[:12]],
        "similar_profiles": similar_profiles,
    }


def _state_plan_card(
    plan: CandidatePlan,
    ranked: RankedPlan | None,
    item_index: dict[str, ScoredPOICandidate],
    state: Any,
) -> dict[str, Any]:
    items = [_state_item_card(slot, item_index.get(slot.poi_id), state) for slot in plan.slots]
    origin = state.constraints.hard_constraints.origin if state.constraints else None
    timeline = _timeline_with_origin(plan, origin)
    warnings = list(
        state.debug.recall_debug.get("availability_plan_warnings", {}).get(plan.plan_id, [])
    )
    score = ranked.plan_score if ranked else 0
    tags = _short_points(
        [
            tag
            for item in items
            for tag in _clean_logic_tags(
                item.get("tags", []),
                str(item.get("logical_category") or ""),
                item.get("subcategory"),
                limit=2,
            )
        ],
        5,
    )
    return {
        "id": plan.plan_id,
        "plan_id": plan.plan_id,
        "title": _plan_title(plan, items, ranked),
        "subtitle": _plan_subtitle(plan),
        "tags": tags,
        "highlight_tags": tags,
        "pros": _short_points(_plan_pros(plan, ranked, items), 4),
        "cons": _short_points(_plan_cons(plan, warnings, items), 3),
        "timeline": timeline,
        "route_segments": _route_segments_for_items(items, origin),
        "route_text": f"交通约 {plan.route_summary.total_route_minutes or 0} 分钟",
        "budget_text": f"预计约 {int(plan.budget_summary.estimated_total_budget or 0)} 元",
        "warnings": warnings,
        "score": score,
        "plan_score": score,
        "rank_features": ranked.rank_features.model_dump(mode="json") if ranked else {},
        "why_recommend": ranked.why_ranked_high if ranked else [],
        "tradeoffs": ranked.tradeoffs if ranked else [],
        "items": items,
        "total_distance_km": plan.route_summary.total_distance_km,
        "route_minutes": plan.route_summary.total_route_minutes,
        "total_duration_minutes": (
            sum(slot.duration_minutes or 0 for slot in plan.slots)
            + (plan.route_summary.total_route_minutes or 0)
        ),
        "estimated_budget": plan.budget_summary.estimated_total_budget,
        "fit_summary": {"budget_fit": plan.budget_summary.budget_fit},
    }


def _timeline_with_origin(plan: CandidatePlan, origin: OriginPoint | None) -> list[dict[str, Any]]:
    timeline = [item.model_dump(mode="json") for item in plan.estimated_timeline]
    if origin is None:
        return timeline
    first_time = timeline[0].get("time_text", "") if timeline else ""
    start_text = str(first_time).split("-", 1)[0] if first_time else ""
    origin_item = {
        "time_text": start_text,
        "title": "起点",
        "description": "出发起点",
        "poi_id": None,
        "type": "origin",
        "source": origin.source,
    }
    return [origin_item, *timeline]


def _state_item_card(slot: PlanSlot, item: ScoredPOICandidate | None, state: Any) -> dict[str, Any]:
    if item is None:
        return {"id": slot.poi_id, "name": slot.poi_name}
    availability = state.plans.availability_results.by_poi.get(item.poi_id)
    return {
        "id": item.poi_id,
        "name": item.name,
        "category": f"poi_{item.logical_category}",
        "logical_category": item.logical_category,
        "subcategory": item.subcategory,
        "lat": item.lat,
        "lon": item.lng,
        "address": item.address,
        "rating": item.rating,
        "avg_price": item.avg_price,
        "image_url": item.image_url,
        "images": item.images,
        "tags": _clean_logic_tags(
            item.logic_tags, item.logical_category, item.subcategory, limit=8
        ),
        "display_category": _category_label(item.logical_category),
        "reason": "、".join(item.reasons[:2]),
        "score": item.final_poi_score,
        "reservation_required": availability.reservation_required if availability else None,
        "reservation_available": availability.reservation_available if availability else None,
        "crowd_risk": availability.queue_risk if availability else None,
        "open_status": availability.open_status if availability else "unknown",
        "risk_flags": item.warnings,
        "start_time": slot.start_time.strftime("%H:%M") if slot.start_time else None,
        "end_time": slot.end_time.strftime("%H:%M") if slot.end_time else None,
    }


def _plan_title(plan: CandidatePlan, items: list[dict[str, Any]], ranked: RankedPlan | None) -> str:
    names = [str(item.get("name") or "") for item in items if item.get("name")]
    if len(names) >= 2:
        return f"{names[0]} + {names[1]}"
    return names[0] if names else f"方案 {ranked.rank if ranked else ''}".strip()


def _plan_subtitle(plan: CandidatePlan) -> str:
    return f"{len(plan.slots)}站 · {plan.route_summary.total_route_minutes or 0}分钟交通"


def _plan_pros(
    plan: CandidatePlan, ranked: RankedPlan | None, items: list[dict[str, Any]]
) -> list[str]:
    pros = list(ranked.why_ranked_high if ranked else [])
    if plan.route_summary.total_route_minutes is not None:
        pros.append("路线清楚")
    if all((item.get("rating") or 0) >= 4.0 for item in items):
        pros.append("评分稳定")
    if plan.budget_summary.budget_fit in {"good", "unknown"}:
        pros.append("预算可控")
    return pros or ["匹配需求"]


def _plan_cons(plan: CandidatePlan, warnings: list[str], items: list[dict[str, Any]]) -> list[str]:
    cons: list[str] = []
    if warnings:
        cons.append("需复核状态")
    if any(item.get("reservation_required") for item in items):
        cons.append("建议预约")
    if plan.budget_summary.budget_fit == "slightly_over":
        cons.append("预算略高")
    if not cons:
        cons.append("营业待确认")
    return cons


def _short_points(values: list[Any], limit: int) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = text[:15]
        if text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result

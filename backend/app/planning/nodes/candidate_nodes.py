from __future__ import annotations

from typing import Any

from app.planning.nodes.common import append_trace, ensure_state
from app.planning.payloads import normalize_response_payload
from app.planning.services.candidate_service import balance_candidates, score_candidates
from app.planning.state import PlanningState


def poi_scorer_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    candidates = state.candidates.model_copy(deep=True)
    session = state.context.session_preference_profile
    memory_tags = [
        *session.activity_preferences,
        *session.dining_preferences,
        *session.soft_preferences,
        *session.preferred_categories,
        *[tag.tag_name for tag in state.context.user_preference_profile.positive_tags],
        *[
            tag
            for cluster in state.context.user_preference_profile.positive_clusters
            for tag in cluster.core_tags
        ],
    ]
    candidates.scored_candidates = score_candidates(candidates.raw_candidates, state.constraints, memory_tags)
    return {"candidates": candidates, "debug": append_trace(state, "poi_scorer", "候选单点评分已完成")}


def candidate_pool_balancer_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    candidates = state.candidates.model_copy(deep=True)
    candidates.balanced_candidates = balance_candidates(candidates.scored_candidates)
    return {
        "candidates": candidates,
        "debug": append_trace(state, "candidate_pool_balancer", "候选池已完成多样性平衡"),
    }


def single_category_ranker_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    items = [item for group in state.candidates.scored_candidates.values() for item in group]
    items.sort(key=lambda item: item.final_poi_score, reverse=True)
    payload = normalize_response_payload({
        "response_type": "poi_list",
        "summary": "为你筛选了匹配地点。",
        "poi_list": [
            {
                "poi_id": item.poi_id,
                "id": item.poi_id,
                "name": item.name,
                "logical_category": item.logical_category,
                "category": f"poi_{item.logical_category}",
                "address": item.address,
                "lat": item.lat,
                "lon": item.lng,
                "rating": item.rating,
                "avg_price": item.avg_price,
                "image_url": item.image_url,
                "images": item.images,
                "tags": item.logic_tags,
                "score": item.final_poi_score,
                "reason": "；".join(item.reasons),
                "reasons": item.reasons,
                "warnings": item.warnings,
            }
            for item in items[:10]
        ],
        "plans": [],
        "selected_plan": {},
    })
    response = state.response.model_copy(deep=True)
    response.response_type = "poi_list"
    response.response_payload = payload
    return {
        "response": response,
        "debug": append_trace(state, "single_category_ranker", f"排序 {len(items)} 个单类候选"),
    }

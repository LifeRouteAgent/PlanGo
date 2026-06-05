from __future__ import annotations

from typing import Any

from app.graph.nodes.common import append_trace, ensure_state
from app.graph.state import (
    CurrentPlanContext,
    PlanningState,
    PreferenceCluster,
    PreferenceTag,
    UserPreferenceProfile,
)
from app.services.memory_service import MemoryService
from app.services.poi_catalog_service import PoiCatalogService
from app.services.session_store import SessionStore


def request_context_loader_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    user = state.user_info.model_copy(deep=True)
    if user.default_origin is None and user.geo_location is not None:
        user.default_origin = {
            "name": "当前位置",
            "lat": user.geo_location.lat,
            "lng": user.geo_location.lng,
            "source": user.geo_location.source,
        }
    context = state.context.model_copy(deep=True)
    context.poi_logical_tag_catalog = PoiCatalogService().load_catalog(
        query=state.context.conversation_context.last_user_message
    )
    return {
        "user_info": user,
        "context": context,
        "debug": append_trace(state, "request_context_loader", "请求上下文和 POI 标签背景知识已标准化"),
    }


def session_state_loader_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    saved = SessionStore().load(state.state_meta.session_id) if state.state_meta.session_id else None
    context = state.context.model_copy(deep=True)
    if saved:
        latest = saved.get("latest_planning_state") or saved.get("latest_state") or {}
        response = saved.get("latest_planning_response") or saved.get("latest_response") or {}
        ranked = response.get("ranked_plans") or latest.get("ranked_plans") or []
        last_intent = str(latest.get("intent_type") or response.get("intent_type") or "")
        context.current_plan_state = CurrentPlanContext(
            has_active_plan=bool(
                ranked
                or response.get("response_payload")
                or last_intent in {"full_trip_plan", "category_recommend", "poi_search"}
            ),
            last_request_type=last_intent or None,
            last_constraints_snapshot=latest.get("constraints") or None,
            last_ranked_plans=ranked[:3],
            selected_or_referenced_plan_id=str((response.get("selected_plan") or {}).get("id") or "") or None,
        )
        turns = saved.get("turns") or []
        context.conversation_context.recent_turns = [
            {"role": "user", "content": str(turn.get("user_query") or "")}
            for turn in turns[-5:]
            if turn.get("user_query")
        ]
    return {"context": context, "debug": append_trace(state, "session_state_loader", "会话摘要已读取")}


def memory_reader_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    memory = MemoryService()
    profile = memory.read_profile(user_id=state.state_meta.user_id or "default")
    similar_profiles = memory.similar_user_preference_search(
        profile,
        user_id=state.state_meta.user_id or "default",
        limit=3,
    )
    context = state.context.model_copy(deep=True)
    favorite = profile.get("favorite_categories") if isinstance(profile.get("favorite_categories"), dict) else {}
    disliked = profile.get("disliked_keywords") if isinstance(profile.get("disliked_keywords"), list) else []
    context.user_preference_profile = UserPreferenceProfile(
        positive_tags=[
            PreferenceTag(
                tag_id=str(name),
                tag_name=str(name),
                confidence=min(1, 0.5 + int(count or 0) * 0.05),
                evidence_count=int(count or 0),
                source="memory",
            )
            for name, count in favorite.items()
        ],
        negative_tags=[
            PreferenceTag(tag_id=str(name), tag_name=str(name), confidence=0.8, source="memory")
            for name in disliked
        ],
        positive_clusters=[
            PreferenceCluster(
                cluster_id=str(item.get("user_id") or f"similar_{index}"),
                cluster_name="similar_user_profile",
                core_tags=[
                    str(tag)
                    for tag in (item.get("metadata", {}) or {}).get("memory_fit_tags", [])
                    if tag
                ][:8],
                similarity_score=float(item.get("score") or 0),
            )
            for index, item in enumerate(similar_profiles, start=1)
            if isinstance(item, dict)
        ],
    )
    return {"context": context, "debug": append_trace(state, "memory_reader", "长期偏好摘要已读取")}

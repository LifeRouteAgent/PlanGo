from __future__ import annotations

from typing import Any

from app.context.context_manager import ContextManager
from app.memory.read_service import MemoryReadService

from app.context.session_store import SessionStore
from app.planning.nodes.common import append_trace
from app.planning.poi_catalog_service import PoiCatalogService
from app.planning.state import (
    PlanningState,
    PreferenceCluster,
    PreferenceTag,
    UserPreferenceProfile,
)


def request_context_loader_node(state: PlanningState) -> dict[str, Any]:
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
        "debug": append_trace(
            state, "request_context_loader", "请求上下文和 POI 标签背景知识已标准化"
        ),
    }


def session_state_loader_node(state: PlanningState) -> dict[str, Any]:
    saved = SessionStore.load(state.state_meta.session_id) if state.state_meta.session_id else None
    context = state.context.model_copy(deep=True)
    context = ContextManager().apply_session_payload(context, saved)
    return {
        "context": context,
        "debug": append_trace(state, "session_state_loader", "会话摘要已读取"),
    }


def memory_reader_node(state: PlanningState) -> dict[str, Any]:
    memory = MemoryReadService()
    profile = memory.read_profile(user_id=state.state_meta.user_id or "default")
    similar_profiles = memory.similar_user_preferences(
        profile,
        user_id=state.state_meta.user_id or "default",
        limit=3,
    )
    context = state.context.model_copy(deep=True)
    favorite = (
        profile.get("favorite_categories")
        if isinstance(profile.get("favorite_categories"), dict)
        else {}
    )
    disliked = (
        profile.get("disliked_keywords")
        if isinstance(profile.get("disliked_keywords"), list)
        else []
    )
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
    context.prompt_context_pack = ContextManager().build_prompt_context_pack(context)
    return {"context": context, "debug": append_trace(state, "memory_reader", "长期偏好摘要已读取")}

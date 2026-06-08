from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.planning.nodes.common import append_trace
from app.planning.services.intent_service import resolve_intent
from app.planning.state import AsyncEventInfo, PlanningState
from app.memory.memory_event_queue import MemoryEventQueue
from app.planning.poi_catalog_service import PoiCatalogService
from app.memory.session_preference_extractor import extract_session_preference_profile
from app.observability.trace_recorder import record_trace_event


def intent_resolver_node(state: PlanningState) -> dict[str, Any]:
    conversation_context = {
        **state.context.current_plan_state.model_dump(mode="json"),
        "prompt_context_pack": state.context.prompt_context_pack,
    }
    understanding = resolve_intent(
        state.context.conversation_context.last_user_message,
        {"user_id": state.state_meta.user_id},
        conversation_context,
        poi_knowledge=PoiCatalogService().background_knowledge(
            state.context.poi_logical_tag_catalog
        ),
    )
    return {
        "llm_understanding": understanding,
        "debug": append_trace(
            state, "intent_resolver", f"请求类型={understanding.intent.request_type}"
        ),
    }


def session_preference_extractor_node(state: PlanningState) -> dict[str, Any]:
    context = state.context.model_copy(deep=True)
    context.session_preference_profile = extract_session_preference_profile(
        state.context.conversation_context.last_user_message,
        state.llm_understanding,
    )
    return {
        "context": context,
        "debug": append_trace(
            state,
            "session_preference_extractor",
            "current request preferences extracted synchronously",
        ),
    }


def async_event_emitter_node(state: PlanningState) -> dict[str, Any]:
    events = state.async_events.model_copy(deep=True)
    MemoryEventQueue().publish_user_query(
        state.context.conversation_context.last_user_message,
        user_id=state.state_meta.user_id or "default",
        trace_id=state.state_meta.request_id,
        run_id=state.state_meta.state_id,
        session_id=state.state_meta.session_id,
    )
    record_trace_event("planning_v2_started", {"state_id": state.state_meta.state_id})
    events.memory_extraction_event = AsyncEventInfo(
        enabled=True, event_id=f"mem_{uuid4().hex}", payload_summary="当前用户消息"
    )
    events.planning_trace_event = AsyncEventInfo(
        enabled=True, event_id=f"trace_{uuid4().hex}", payload_summary="Planning Graph V2"
    )
    return {
        "async_events": events,
        "debug": append_trace(state, "async_event_emitter", "异步事件已投递"),
    }


def request_router_node(state: PlanningState) -> dict[str, Any]:
    return {"debug": append_trace(state, "request_router", "请求分支已选择")}


def request_route(state: PlanningState) -> str:
    return (
        state.llm_understanding.intent.request_type
        if state.llm_understanding
        else "full_itinerary_plan"
    )

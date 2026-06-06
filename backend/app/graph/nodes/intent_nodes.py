from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.graph.nodes.common import append_trace, ensure_state
from app.graph.services.intent_service import resolve_intent
from app.graph.state import AsyncEventInfo, PlanningState
from app.services.memory_event_queue import MemoryEventQueue
from app.services.poi_catalog_service import PoiCatalogService
from app.services.session_preference_extractor import extract_session_preference_profile
from app.services.trace_recorder import record_trace_event


def intent_resolver_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    understanding = resolve_intent(
        state.context.conversation_context.last_user_message,
        {"user_id": state.state_meta.user_id},
        state.context.current_plan_state.model_dump(mode="json"),
        poi_knowledge=PoiCatalogService().background_knowledge(state.context.poi_logical_tag_catalog),
    )
    return {
        "llm_understanding": understanding,
        "debug": append_trace(state, "intent_resolver", f"请求类型={understanding.intent.request_type}"),
    }


def session_preference_extractor_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
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


def async_event_emitter_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
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
    return {"async_events": events, "debug": append_trace(state, "async_event_emitter", "异步事件已投递")}


def request_router_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    return {"debug": append_trace(state, "request_router", "请求分支已选择")}


def request_route(value: PlanningState | dict[str, Any]) -> str:
    state = ensure_state(value)
    return state.llm_understanding.intent.request_type if state.llm_understanding else "full_itinerary_plan"

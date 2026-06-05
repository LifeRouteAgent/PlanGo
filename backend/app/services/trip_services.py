from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from typing import Any

from app.bus.event import Event
from app.bus.event_bus import publish_event_sync
from app.bus.subscribers.frontend_subscriber import install_frontend_progress_subscriber
from app.graph.graph_builder import planning_graph_v2
from app.graph.state import PlanningState, create_planning_state, planning_state_to_legacy
from app.models.schemas import RevisePlanRequest, TripPlanRequest, TripPlanResponse
from app.services.checkpoint_store import CheckpointStore, TaskStatus
from app.services.amap_weather_service import AmapWeatherService
from app.services.memory_service import MemoryService
from app.services.policy_config import policy_config
from app.services.runtime_store import get_runtime_store
from app.services.session_store import SessionStore
from app.services.trace_recorder import new_id, set_trace_context
from app.services.trip_progress import build_agent_thinking_payload
from app.streaming.stream_manager import stream_manager

install_frontend_progress_subscriber()


class TripPlanningService:
    """Planning Graph V2 同步入口。"""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,
        memory: MemoryService | None = None,
        checkpoint: CheckpointStore | None = None,
    ) -> None:
        self.session_store = session_store or SessionStore()
        self.memory = memory or MemoryService()
        self.checkpoint = checkpoint or CheckpointStore()

    def plan(self, request: TripPlanRequest) -> TripPlanResponse:
        session_id = self.session_store.ensure_session_id(request.session_id)
        trace_id = request.trace_id or new_id("trace")
        run_id = request.run_id or new_id("run")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
        task = self.checkpoint.create(session_id=session_id, user_id=request.user_id or session_id, trace_id=trace_id)
        result = run_v2_request_to_legacy(request, session_id=session_id)
        result.update({"task_id": str(task["task_id"]), "trace_id": trace_id, "run_id": run_id, "session_id": session_id})
        self.checkpoint.save_from_plan_state(
            result,
            status=checkpoint_status_from_state(result),
            task_id=str(task["task_id"]),
        )
        response = build_trip_response(result, include_debug=request.debug)
        self.session_store.save_turn(
            session_id=session_id,
            trace_id=trace_id,
            run_id=run_id,
            user_query=request.user_query,
            state=result,
            response=response.model_dump(),
        )
        return response


class TripStreamingService:
    """Planning Graph V2 SSE 入口。"""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,
        memory: MemoryService | None = None,
        checkpoint: CheckpointStore | None = None,
    ) -> None:
        self.session_store = session_store or SessionStore()
        self.memory = memory or MemoryService()
        self.checkpoint = checkpoint or CheckpointStore()

    def stream(self, request: TripPlanRequest) -> Iterator[str]:
        yield from stream_v2_request(request)


class TripRevisionService:
    """修订请求统一进入 V2 plan_adjustment 分支。"""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,
        memory: MemoryService | None = None,
        checkpoint: CheckpointStore | None = None,
    ) -> None:
        self.session_store = session_store or SessionStore()
        self.memory = memory or MemoryService()
        self.checkpoint = checkpoint or CheckpointStore()

    def stream(self, request: RevisePlanRequest) -> Iterator[str]:
        yield from stream_v2_request(
            TripPlanRequest(
                user_query=request.user_query,
                session_id=request.session_id,
                max_replanning_count=request.max_replanning_count,
            )
        )


class TripExecutionService:
    def risk_level_for_step(self, step: dict[str, Any]) -> int:
        action_type = str(step.get("type") or step.get("action_type") or "")
        return policy_config.risk_policy.risk_level_for(action_type, default=1)

    def validated_item_ids(self, plan: dict[str, Any]) -> list[str]:
        return [
            str(item.get("id"))
            for item in plan.get("items", [])
            if isinstance(item, dict) and item.get("id")
        ]


class TaskRecoveryService:
    def __init__(self, checkpoint: CheckpointStore | None = None) -> None:
        self.checkpoint = checkpoint or CheckpointStore()

    def task_payload(self, task_id: str) -> dict[str, Any]:
        task = self.checkpoint.load(task_id)
        return {"ok": bool(task), "task": task}

    def resume_decision(self, task_id: str) -> dict[str, Any]:
        return self.checkpoint.resume(task_id)

    def runtime_summary(self) -> dict[str, Any]:
        runtime = get_runtime_store()
        tasks = runtime.list_tasks()
        metrics = runtime.list_node_metrics()
        return {
            "task_count": len(tasks),
            "trace_count": len({item.get("trace_id") for item in metrics if item.get("trace_id")}),
            "node_metric_count": len(metrics),
            "recoverable_task_count": len(self.checkpoint.recoverable_tasks()),
        }

    def node_metrics(self, trace_id: str | None = None) -> dict[str, Any]:
        metrics = get_runtime_store().list_node_metrics(trace_id)
        return {"trace_id": trace_id or "", "count": len(metrics), "metrics": metrics}

    def runtime_health(self) -> dict[str, Any]:
        return get_runtime_store().health()


def run_v2_request_to_legacy(request: TripPlanRequest, *, session_id: str) -> dict[str, Any]:
    initial = create_v2_initial_state(request, session_id=session_id)
    return run_v2_state_to_legacy(initial)


def create_v2_initial_state(request: TripPlanRequest, *, session_id: str) -> PlanningState:
    return create_planning_state(
        request.user_query,
        session_id=session_id,
        user_id=request.user_id or session_id,
        city=str(request.user_profile.get("city") or "") or None,
        message_id=request.message_id or "",
        timezone=request.timezone,
        source=request.source,
        geo_location=request.geo_location,
        manual_origin=request.manual_origin,
    )


def run_v2_state_to_legacy(initial: PlanningState) -> dict[str, Any]:
    _publish_run_event(initial, "run_started", status="running")
    try:
        result = planning_graph_v2.invoke(initial)
        state = result if isinstance(result, PlanningState) else PlanningState.model_validate(result)
        legacy = planning_state_to_legacy(state)
        _publish_run_event(
            state,
            "run_finished",
            status="success",
            payload={
                "plan_count": len(legacy.get("ranked_plans") or []),
                "request_type": legacy.get("intent_type"),
            },
        )
        return legacy
    except Exception as exc:
        _publish_run_event(
            initial,
            "run_failed",
            status="failed",
            payload={"error_summary": exc.__class__.__name__},
        )
        raise


def start_v2_plan_progress(request: TripPlanRequest) -> dict[str, str]:
    session_id = SessionStore().ensure_session_id(request.session_id)
    initial = create_v2_initial_state(request, session_id=session_id)
    request_id = initial.state_meta.request_id
    stream_manager.register(request_id)

    thread = threading.Thread(
        target=_run_v2_progress_job,
        args=(initial,),
        name=f"planning-progress-{request_id}",
        daemon=True,
    )
    thread.start()
    return {
        "request_id": request_id,
        "run_id": initial.state_meta.state_id,
        "stream_url": f"/api/plans/{request_id}/stream",
    }


def _run_v2_progress_job(initial: PlanningState) -> None:
    try:
        legacy = run_v2_state_to_legacy(initial)
        legacy["session_id"] = initial.state_meta.session_id
        response = build_trip_response(legacy)
        import asyncio

        asyncio.run(stream_manager.send(initial.state_meta.request_id, {
            "type": "final_result",
            "request_id": initial.state_meta.request_id,
            "run_id": initial.state_meta.state_id,
            "response": response.model_dump(mode="json"),
        }))
    finally:
        import asyncio

        asyncio.run(stream_manager.close(initial.state_meta.request_id))


def _publish_run_event(
    state: PlanningState,
    event_type: str,
    *,
    status: str,
    payload: dict[str, Any] | None = None,
) -> None:
    publish_event_sync(
        Event(
            event_type=event_type,
            request_id=state.state_meta.request_id,
            run_id=state.state_meta.state_id,
            conversation_id=state.state_meta.session_id or None,
            user_id=state.state_meta.user_id or None,
            status=status,
            payload=payload or {},
        )
    )


def stream_v2_request(request: TripPlanRequest) -> Iterator[str]:
    session_id = SessionStore().ensure_session_id(request.session_id)
    initial = create_planning_state(
        request.user_query,
        session_id=session_id,
        user_id=request.user_id or session_id,
        city=str(request.user_profile.get("city") or "") or None,
        message_id=request.message_id or "",
        timezone=request.timezone,
        source=request.source,
        geo_location=request.geo_location,
        manual_origin=request.manual_origin,
    )
    current = initial
    yield sse_event("status", {"stage": "planning_v2", "session_id": session_id, "message": "Planning Graph V2 已启动。"})
    for update in planning_graph_v2.stream(initial, stream_mode="updates"):
        for node_name, patch in update.items():
            payload = current.model_dump(mode="python")
            payload.update(patch)
            current = PlanningState.model_validate(payload)
            yield sse_event(
                "agent_thinking",
                build_agent_thinking_payload(node_name, patch, current.model_dump(mode="json")),
            )
            yield sse_event("node_update", {"node": node_name, "message": f"{node_name} completed", "duration_ms": 0})
    legacy = planning_state_to_legacy(current)
    legacy["session_id"] = session_id
    response = build_trip_response(legacy, include_debug=request.debug)
    for chunk in chunk_text(response.response_text):
        yield sse_event("response_chunk", {"delta": chunk})
    yield sse_event("final", response.model_dump())
    yield sse_event("done", {"ok": True})


def build_trip_response(result: dict[str, Any], *, include_debug: bool = False) -> TripPlanResponse:
    result = attach_frontend_compatibility(result)
    return TripPlanResponse(
        response_text=result.get("response_text", ""),
        execution_status=result.get("execution_status", "unknown"),
        intent_type=result.get("intent_type", ""),
        answer_mode=result.get("answer_mode", ""),
        need_clarification=False,
        selected_plan=result.get("selected_plan", {}),
        ranked_plans=result.get("ranked_plans", []),
        errors=result.get("errors", []),
        logs=result.get("logs", []),
        session_id=result.get("session_id", ""),
        trace_id=result.get("trace_id", ""),
        run_id=result.get("run_id", ""),
        revision_id=result.get("revision_id", ""),
        is_revision=bool(result.get("is_revision", False)),
        task_id=result.get("task_id", ""),
        final_text=result.get("final_text") or result.get("response_text", ""),
        response_payload=result.get("response_payload", {}),
        plan_state_id=result.get("plan_state_id", ""),
        constraints=result.get("constraints", {}),
        target_categories=result.get("target_categories", []),
        weather=result.get("weather", {}),
        routes=result.get("routes", []),
        debug=result.get("debug", {}) if include_debug else {},
    )


def attach_frontend_compatibility(result: dict[str, Any]) -> dict[str, Any]:
    ranked = [dict(plan) for plan in result.get("ranked_plans", []) if isinstance(plan, dict)]
    selected = dict(result.get("selected_plan") or {})
    if not ranked and not selected:
        return result
    city = str((result.get("constraints") or {}).get("city") or "北京")
    weather = AmapWeatherService().current_weather(city)
    ranked = [{**plan, "weather": weather} for plan in ranked]
    if selected:
        selected["weather"] = weather
    routes = [
        {"plan_id": plan.get("id") or plan.get("plan_id"), "segments": plan.get("route_segments", [])}
        for plan in ranked
    ]
    return {**result, "ranked_plans": ranked, "selected_plan": selected, "weather": weather, "routes": routes}


def checkpoint_status_from_state(state: dict[str, Any]) -> TaskStatus:
    if state.get("selected_plan") or state.get("ranked_plans"):
        return TaskStatus.PLAN_VALIDATED
    if state.get("response_text"):
        return TaskStatus.INTENT_PARSED
    return TaskStatus.CREATED


def effective_query_for_request(saved_session: dict[str, Any] | None, current_query: str) -> str:
    """V2 不拼接旧 query；会话摘要由 session_state_loader 读取。"""

    return current_query


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def chunk_text(text: str, chunk_size: int = 18) -> Iterator[str]:
    for index in range(0, len(text or ""), chunk_size):
        yield text[index : index + chunk_size]

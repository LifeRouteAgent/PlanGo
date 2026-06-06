from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from app.config import settings
from app.api.schemas.trip import (
    AdjustPlanRequest,
    DataSourceStatusResponse,
    ExecutePlanRequest,
    RevisePlanRequest,
    TripPlanRequest,
    TripPlanResponse,
)
from app.integrations.calendar_service import build_plan_ics
from app.runtime.checkpoint_store import CheckpointStore, TaskStatus, make_idempotency_key
from app.memory.memory_event_queue import MemoryEventQueue
from app.memory.memory_service import MemoryService
from app.repositories.poi_repository import PoiRepository
from app.observability.trace_recorder import TraceRecorder, new_id, record_trace_event, set_trace_context
from app.planning.trip_services import (
    TaskRecoveryService,
    TripExecutionService,
    TripPlanningService,
    TripRevisionService,
    TripStreamingService,
)
from app.observability.trip_progress import (
    build_agent_thinking_payload as _build_agent_thinking_payload,
    effective_query_for_request as _effective_query_for_request,
    trace_events_for_node as _trace_events_for_node,
)

router = APIRouter(prefix="/trip", tags=["trip"])


@router.get("/client-config")
def get_client_config() -> dict[str, str]:
    return {"amap_key": settings.amap_api_key, "amap_security_js_code": ""}


@router.post("/plan", response_model=TripPlanResponse)
def plan_trip(request: TripPlanRequest) -> TripPlanResponse:
    return TripPlanningService().plan(request)


@router.post("/plan/stream")
def stream_plan_trip(request: TripPlanRequest) -> StreamingResponse:
    return _streaming_response(TripStreamingService().stream(request))


@router.post("/plan/revise/stream")
def stream_revise_plan(request: RevisePlanRequest) -> StreamingResponse:
    return _streaming_response(TripRevisionService().stream(request))


@router.post("/execute/stream")
def stream_execute_plan(request: ExecutePlanRequest) -> StreamingResponse:
    """只模拟执行，不调用真实预约、购票、打车或支付接口。"""

    def events() -> Iterator[str]:
        session_id = request.session_id or "execution_session"
        trace_id = request.trace_id or new_id("trace")
        run_id = request.run_id or new_id("run")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
        checkpoint = CheckpointStore()
        task_id = request.task_id or str(request.plan.get("task_id") or new_id("task"))
        if not checkpoint.load(task_id):
            checkpoint.create(session_id=session_id, user_id=session_id, trace_id=trace_id, task_id=task_id)
        steps = _execution_steps(request.plan)
        yield _sse("execution_start", {"plan_id": request.plan.get("id"), "total_steps": len(steps), "task_id": task_id})
        service = TripExecutionService()
        valid_ids = service.validated_item_ids(request.plan)
        for step in steps:
            risk = service.risk_level_for_step(step)
            target_id = str(step.get("poi_id") or step.get("id") or request.plan.get("id") or "")
            key = make_idempotency_key(
                user_id=session_id,
                task_id=task_id,
                action_type=str(step.get("type") or "step"),
                target_id=target_id,
            )
            checkpoint.append_action(task_id, {
                "action_id": str(step["id"]),
                "type": str(step["type"]),
                "risk_level": int(risk),
                "status": "running",
                "idempotency_key": key,
                "request": {**step, "validated_item_ids": valid_ids},
                "result": None,
            })
            yield _sse("execution_step", {**step, "status": "running"})
            time.sleep(0.15)
            checkpoint.append_action(task_id, {
                "action_id": str(step["id"]),
                "type": str(step["type"]),
                "risk_level": int(risk),
                "status": "success",
                "idempotency_key": key,
                "request": step,
                "result": {"simulated": True},
            })
            yield _sse("execution_step", {**step, "status": "done", "result": "模拟执行完成"})
        MemoryEventQueue().publish_plan_feedback(
            request.plan,
            user_id=session_id,
            stage="plan_executed",
            feedback={"source": "execute_stream"},
            trace_id=trace_id,
            run_id=run_id,
            session_id=session_id,
        )
        yield _sse("execution_done", {"status": "done", "message": "模拟执行完成，未调用真实第三方 API。"})

    return _streaming_response(events())


@router.post("/plan/adjust")
def adjust_plan(request: AdjustPlanRequest) -> dict[str, Any]:
    """兼容旧前端的单站替换；多轮调整应使用 V2 plan_adjustment。"""

    plan = dict(request.plan)
    items = [dict(item) for item in plan.get("items", []) if isinstance(item, dict)]
    index = next((i for i, item in enumerate(items) if str(item.get("id")) == request.poi_id), None)
    if index is None:
        return {"ok": False, "plan": plan, "message": "没有找到要替换的地点。"}
    old = items[index]
    alternatives = PoiRepository(limit_per_category=10).fetch_by_categories([str(old.get("category") or "")])
    replacement = next(
        (dict(item) for item in alternatives.get(str(old.get("category") or ""), []) if str(item.get("id")) != request.poi_id),
        None,
    )
    if replacement is None:
        return {"ok": False, "plan": plan, "message": "当前类别没有可替换候选。"}
    items[index] = replacement
    plan.update({
        "items": items,
        "title": f"{plan.get('title', '方案')}（已局部调整）",
        "recommendation_reason": f"已按“{request.prompt}”替换单站，建议重新确认路线和预算。",
    })
    return {"ok": True, "plan": plan, "message": "已完成单站替换。", "issues": plan.get("issues", [])}


@router.post("/calendar/ics")
def export_calendar_ics(request: ExecutePlanRequest) -> Response:
    ics_text = build_plan_ics(request.plan)
    if request.session_id:
        MemoryEventQueue().publish_plan_feedback(
            request.plan,
            user_id=request.session_id,
            stage="plan_exported_calendar",
            feedback={"source": "calendar_ics"},
            trace_id=request.trace_id or "",
            run_id=request.run_id or "",
            session_id=request.session_id,
        )
    return Response(
        content=ics_text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="liferoute-plan.ics"'},
    )


@router.get("/trace/{trace_id}")
def get_trace(trace_id: str) -> dict[str, Any]:
    return TraceRecorder.read(trace_id)


@router.get("/task/{task_id}")
def get_task_checkpoint(task_id: str) -> dict[str, Any]:
    return TaskRecoveryService().task_payload(task_id)


@router.post("/task/{task_id}/resume")
def resume_task_checkpoint(task_id: str) -> dict[str, Any]:
    return TaskRecoveryService().resume_decision(task_id)


@router.get("/task/{task_id}/resume-decision")
def get_task_resume_decision(task_id: str) -> dict[str, Any]:
    return TaskRecoveryService().resume_decision(task_id)


@router.get("/evals/runtime-summary")
def get_runtime_eval_summary() -> dict[str, Any]:
    return TaskRecoveryService().runtime_summary()


@router.get("/observability/node-metrics")
def get_node_metrics(trace_id: str | None = Query(default=None)) -> dict[str, Any]:
    return TaskRecoveryService().node_metrics(trace_id)


@router.get("/observability/runtime-health")
def get_runtime_health() -> dict[str, Any]:
    return TaskRecoveryService().runtime_health()


@router.delete("/memory")
def clear_memory(user_id: str | None = Query(default=None)) -> dict[str, Any]:
    MemoryService().clear(user_id=user_id or "default")
    return {"ok": True}


@router.get("/memory/search")
def search_memory(query: str = Query(default=""), limit: int = Query(default=5, ge=1, le=20), user_id: str = Query(default="default")) -> dict[str, Any]:
    return {"items": MemoryService().semantic_search(query, limit=limit, user_id=user_id)}


@router.get("/memory/profile")
def get_memory_profile(user_id: str = Query(default="default")) -> dict[str, Any]:
    return MemoryService().profile_payload(user_id=user_id)


@router.post("/memory/rebuild-index")
def rebuild_memory_index(user_id: str = Query(default="default")) -> dict[str, Any]:
    return MemoryService().rebuild_vector_index(user_id=user_id)


@router.get("/memory/clusters")
def get_memory_clusters() -> dict[str, Any]:
    return {"clusters": MemoryService().clusters()}


@router.get("/data-source", response_model=DataSourceStatusResponse)
def data_source_status() -> DataSourceStatusResponse:
    try:
        counts = PoiRepository().table_counts()
        return DataSourceStatusResponse(
            enabled=settings.use_database,
            source="mysql" if settings.use_database else "mock",
            database_name=settings.database_name,
            table_counts=counts,
        )
    except Exception as exc:  # noqa: BLE001
        return DataSourceStatusResponse(
            enabled=False,
            source="unavailable",
            database_name=settings.database_name,
            error=str(exc),
        )


def _streaming_response(events: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _execution_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [
        {
            "id": f"visit_{index}",
            "type": "visit",
            "poi_id": item.get("id"),
            "title": f"确认前往 {item.get('name')}",
        }
        for index, item in enumerate(plan.get("items", []), start=1)
        if isinstance(item, dict)
    ]
    steps.append({"id": "calendar_export", "type": "calendar_export", "title": "生成日历提醒"})
    return steps

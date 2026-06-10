from __future__ import annotations

from typing import Any

from app.bus.event import Event, EventType
from app.bus.subscribers.constants import NODE_STARTED_MESSAGES, BUSINESS_MESSAGES
from app.streaming.schemas import FrontendProgressEvent


def _progress(
    event: Event,
    title: str,
    message: str,
    status: str,
    *,
    step: str | None = None,
    event_type: str = "progress",
    data: dict[str, Any] | None = None,
) -> FrontendProgressEvent:
    return FrontendProgressEvent(
        type=event_type,
        title=title,
        message=message,
        status=status,
        step=step,
        request_id=event.request_id,
        run_id=event.run_id,
        timestamp=event.timestamp,
        data=data or {},
    )


class ProgressProjector:
    """Project internal Event into user-readable frontend progress."""

    @staticmethod
    def project(event: Event) -> FrontendProgressEvent | None:
        if event.event_type == EventType.NODE_STARTED and event.node_name:
            title, message = NODE_STARTED_MESSAGES.get(
                event.node_name, ("正在处理规划步骤", "系统正在继续处理你的规划请求。")
            )
            return _progress(event, title, message, "running", step=event.node_name)

        if event.event_type == EventType.NODE_FAILED:
            return _progress(
                event,
                "步骤暂时不可用",
                "部分步骤处理失败，系统会尽量使用可用信息继续规划。",
                "warning",
                step=event.node_name,
                event_type="warning",
            )

        if event.event_type in BUSINESS_MESSAGES:
            frontend_type, title, message = BUSINESS_MESSAGES[event.event_type]
            status = _status_for(event.event_type, frontend_type)
            data = _safe_frontend_data(event.payload)
            return _progress(
                event,
                title,
                _format_message(message, data),
                status,
                step=event.node_name,
                event_type=frontend_type,
                data=data,
            )
        return None


def _status_for(event_type: EventType, frontend_type: str) -> str:
    if frontend_type == "error":
        return "failed"
    if frontend_type == "warning":
        return "warning"
    if event_type == EventType.RUN_FINISHED:
        return "success"
    return (
        "running"
        if event_type
        not in {EventType.INTENT_PARSED, EventType.SLOTS_GENERATED, EventType.PLAN_RANKED}
        else "success"
    )


def _safe_frontend_data(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "available_plan_count",
        "balanced_counts",
        "category_count",
        "failure_reason",
        "plan_count",
        "query_count",
        "request_type",
        "slot_count",
        "target_categories",
        "total_count",
    }
    return {key: value for key, value in payload.items() if key in allowed}


def _format_message(message: str, data: dict[str, Any]) -> str:
    if "total_count" in data:
        return f"已找到 {data['total_count']} 个候选地点，正在继续筛选。"
    if "plan_count" in data:
        return f"已组合出 {data['plan_count']} 个初步方案，正在检查可执行性。"
    if "available_plan_count" in data:
        return f"已有 {data['available_plan_count']} 个方案通过可用性检查。"
    return message

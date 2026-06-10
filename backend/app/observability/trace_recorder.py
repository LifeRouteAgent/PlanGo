from __future__ import annotations

import contextvars
import time
import uuid
from typing import Any, TypeVar

import loguru

from app.runtime.runtime_store import NodeMetricRecord, get_runtime_store

T = TypeVar("T")

_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "liferoute_trace_id", default=None
)
_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "liferoute_run_id", default=None
)
_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "liferoute_session_id", default=None
)


def new_id(prefix: str) -> str:
    """生成短而可读的运行 ID。"""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def set_trace_context(*, trace_id: str | None, run_id: str | None, session_id: str | None) -> None:
    """把当前请求的 trace 上下文绑定到 contextvars，供 ToolHarness 自动读取。"""

    _current_trace_id.set(trace_id)
    _current_run_id.set(run_id)
    _current_session_id.set(session_id)


class TraceRecorder:
    """文件型 trace 记录器。

    每个 trace 对应一个 JSONL 文件，事件 append-only 写入，便于 demo 时直接查看，
    也方便后续迁移到 OpenTelemetry、数据库或日志系统。

    静态方法 record 是主要入口——从 contextvars 读取 trace 上下文，无需创建实例。
    """

    @staticmethod
    def record(trace_type: str, trace_info: dict[str, Any]):
        """写入一条 trace 事件，trace 上下文从 contextvars 读取。"""
        trace_id = _current_trace_id.get()
        run_id = _current_run_id.get()
        session_id = _current_session_id.get()
        if not trace_id or not run_id or not session_id:
            return

        trace = {
            "event_type": trace_type,
            "trace_id": trace_id,
            "run_id": run_id,
            "session_id": session_id,
            "timestamp": time.time(),
            **trace_info,
        }
        runtime_store = get_runtime_store()
        runtime_store.append_trace_event(trace_id, trace)
        if trace_type == "node_run":
            runtime_store.record_node_metric(
                NodeMetricRecord(
                    trace_id=trace_id,
                    run_id=run_id,
                    session_id=session_id,
                    node_name=str(trace_info.get("node_name") or ""),
                    started_at=float(trace_info.get("started_at") or trace["timestamp"]),
                    ended_at=float(trace_info.get("ended_at") or trace["timestamp"]),
                    duration_ms=int(trace_info.get("duration_ms", 0) or 0),
                    status="failed" if trace_info.get("error") else "success",
                    error=trace_info.get("error"),
                    output_summary=trace_info.get("output_summary", {}),
                )
            )
        else:
            loguru.logger.info("trace_type={!r} 非 node_run 类型, 不予记录", trace_type)

    @staticmethod
    def read(trace_id: str) -> dict[str, Any]:
        """读取 trace 摘要和事件列表。"""

        events = get_runtime_store().read_trace_events(trace_id)
        if not events:
            return {"trace_id": trace_id, "events": [], "summary": {"event_count": 0}}
        node_events = [event for event in events if event.get("event_type") == "node_run"]
        tool_events = [event for event in events if event.get("event_type") == "tool_call"]
        return {
            "trace_id": trace_id,
            "events": events,
            "summary": {
                "event_count": len(events),
                "node_count": len(node_events),
                "tool_count": len(tool_events),
                "duration_ms": sum(int(event.get("duration_ms", 0) or 0) for event in node_events),
            },
        }

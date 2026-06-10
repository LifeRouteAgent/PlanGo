from __future__ import annotations

from time import perf_counter
from typing import Any

from app.observability.trace_recorder import new_id, TraceRecorder


def new_trace_id() -> str:
    """生成规划链路 trace_id。

    先复用现有 trace_recorder 的 ID 规则，后续如果替换 tracing backend，
    只需要改 core 层，不影响 graph node。
    """

    return new_id("trace")


def record_node_event(
    *,
    trace_id: str,
    session_id: str = "",
    node: str,
    event: str,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """记录结构化节点事件。

    只写摘要，不写用户原文、精确经纬度、SQL 或 LLM 完整输出。
    """

    TraceRecorder.record(
        "graph_node_event",
        {
            "trace_id": trace_id,
            "session_id": session_id,
            "node": node,
            "event": event,
            "duration_ms": duration_ms,
            "input_summary": input_summary or {},
            "output_summary": output_summary or {},
            "details": details or {},
        },
    )


class NodeTraceSpan:
    """节点耗时上下文。

    用法：
        with NodeTraceSpan(trace_id=..., node="collector") as span:
            ...
            span.output_summary = {"candidate_count": 42}
    """

    def __init__(
        self,
        *,
        trace_id: str,
        node: str,
        session_id: str = "",
        input_summary: dict[str, Any] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.node = node
        self.session_id = session_id
        self.input_summary = input_summary or {}
        self.output_summary: dict[str, Any] = {}
        self._start = 0.0

    def __enter__(self) -> "NodeTraceSpan":
        self._start = perf_counter()
        record_node_event(
            trace_id=self.trace_id,
            session_id=self.session_id,
            node=self.node,
            event="node_start",
            input_summary=self.input_summary,
        )
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        duration_ms = int((perf_counter() - self._start) * 1000)
        if exc is not None:
            record_node_event(
                trace_id=self.trace_id,
                session_id=self.session_id,
                node=self.node,
                event="node_error",
                input_summary=self.input_summary,
                duration_ms=duration_ms,
                details={"error_type": type(exc).__name__},
            )
            return False
        record_node_event(
            trace_id=self.trace_id,
            session_id=self.session_id,
            node=self.node,
            event="node_end",
            input_summary=self.input_summary,
            output_summary=self.output_summary,
            duration_ms=duration_ms,
        )
        return False

from __future__ import annotations

import contextvars
import json
import time
import uuid
from collections.abc import Callable
from typing import Any, TypeVar

from app.services.runtime_paths import TRACES_DIR, ensure_runtime_dirs

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


def set_trace_context(
    *,
    trace_id: str | None,
    run_id: str | None,
    session_id: str | None,
) -> None:
    """把当前请求的 trace 上下文绑定到 contextvars，供 ToolHarness 自动读取。"""

    _current_trace_id.set(trace_id)
    _current_run_id.set(run_id)
    _current_session_id.set(session_id)


def current_trace_context() -> dict[str, str | None]:
    """读取当前线程/上下文中的 trace 标识。"""

    return {
        "trace_id": _current_trace_id.get(),
        "run_id": _current_run_id.get(),
        "session_id": _current_session_id.get(),
    }


class TraceRecorder:
    """文件型 trace 记录器。

    每个 trace 对应一个 JSONL 文件，事件 append-only 写入，便于 demo 时直接查看，
    也方便后续迁移到 OpenTelemetry、数据库或日志系统。
    """

    def __init__(self, *, trace_id: str, run_id: str, session_id: str):
        ensure_runtime_dirs()
        self.trace_id = trace_id
        self.run_id = run_id
        self.session_id = session_id
        self.path = TRACES_DIR / f"{trace_id}.jsonl"

    def record(self, event_type: str, payload: dict[str, Any]):
        """写入一条 trace 事件。"""

        event = {
            "event_type": event_type,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "timestamp": time.time(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def time_node(
        self, node_name: str, fn: Callable[[], T], *, input_summary: dict[str, Any] | None = None
    ) -> T:
        """记录 LangGraph 节点耗时，并把异常也写入 trace。"""

        started = time.time()
        try:
            result = fn()
            ended = time.time()
            # todo: 这个函数调用参数和 expect 里面的基本一致, 能否优化一下呢?
            self.record(
                "node_run",
                {
                    "node_name": node_name,
                    "started_at": started,
                    "ended_at": ended,
                    "duration_ms": int((ended - started) * 1000),
                    "input_summary": input_summary or {},
                    "output_summary": summarize_state_patch(result),
                    "error": None,
                },
            )
            return result
        except Exception as exc:
            ended = time.time()
            self.record(
                "node_run",
                {
                    "node_name": node_name,
                    "started_at": started,
                    "ended_at": ended,
                    "duration_ms": int((ended - started) * 1000),
                    "input_summary": input_summary or {},
                    "output_summary": {},
                    "error": str(exc),
                },
            )
            raise

    @staticmethod
    def read(trace_id: str) -> dict[str, Any]:
        """读取 trace 摘要和事件列表。"""

        ensure_runtime_dirs()
        path = TRACES_DIR / f"{trace_id}.jsonl"
        if not path.exists():
            return {"trace_id": trace_id, "events": [], "summary": {"event_count": 0}}
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
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


# todo: 如果把这个函数作为 `TraceRecorder` 的静态方法是不是更好一些?
def record_trace_event(event_type: str, payload: dict[str, Any]):
    """供 ToolHarness 等底层服务在不知道 recorder 实例时写 trace。"""

    context = current_trace_context()
    trace_id = context.get("trace_id")
    run_id = context.get("run_id")
    session_id = context.get("session_id")
    if not trace_id or not run_id or not session_id:
        return
    TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=session_id).record(
        event_type, payload
    )


def summarize_state_patch(value: Any) -> dict[str, Any]:
    """把节点输出压缩成可观测摘要，避免 trace 文件写入完整 POI 列表。"""

    if not isinstance(value, dict):
        return {"type": type(value).__name__}
    return {
        "keys": sorted(value.keys()),
        "candidate_categories": (
            list(value.get("candidate_pois", {}).keys())
            if isinstance(value.get("candidate_pois"), dict)
            else []
        ),
        "recommended_categories": (
            list(value.get("recommended_pois", {}).keys())
            if isinstance(value.get("recommended_pois"), dict)
            else []
        ),
        "candidate_plan_count": (
            len(value.get("candidate_plans", []))
            if isinstance(value.get("candidate_plans"), list)
            else 0
        ),
        "verified_plan_count": (
            len(value.get("verified_plans", []))
            if isinstance(value.get("verified_plans"), list)
            else 0
        ),
        "ranked_plan_count": (
            len(value.get("ranked_plans", [])) if isinstance(value.get("ranked_plans"), list) else 0
        ),
        "error_count": len(value.get("errors", [])) if isinstance(value.get("errors"), list) else 0,
    }

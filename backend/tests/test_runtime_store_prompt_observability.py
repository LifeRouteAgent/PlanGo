from __future__ import annotations

from app.api.schemas.trip import TripPlanRequest
from app.llm.prompt_registry import get_prompt_spec
from app.runtime.runtime_store import FileRuntimeStore, get_runtime_store
from app.observability.trace_recorder import TraceRecorder
from app.planning.trip_services import (
    TripPlanningService,
    TripRevisionService,
    TripStreamingService,
)


def test_file_runtime_store_roundtrip_core_records() -> None:
    """文件 fallback 与 MySQL store 使用同一组核心接口。"""

    store = FileRuntimeStore()
    store.save_session("sess_runtime_unit", {"session_id": "sess_runtime_unit", "value": 1})
    store.save_task("task_runtime_unit", {"task_id": "task_runtime_unit", "status": "CREATED"})
    store.put_tool_cache(
        "cache_runtime_unit",
        {
            "cache_key": "cache_runtime_unit",
            "tool_name": "unit.tool",
            "request_hash": "hash",
            "result_summary": {"ok": True},
            "expires_at": "2999-01-01T00:00:00Z",
        },
    )

    assert store.load_session("sess_runtime_unit")["value"] == 1
    assert store.load_task("task_runtime_unit")["status"] == "CREATED"
    assert store.get_tool_cache("cache_runtime_unit")["tool_name"] == "unit.tool"


def test_trace_recorder_writes_node_metrics() -> None:
    """节点 trace 要同步写入 node metric，供观测面板做耗时排序。"""

    recorder = TraceRecorder(
        trace_id="trace_metric_unit",
        run_id="run_metric_unit",
        session_id="sess_metric_unit",
    )
    recorder.record(
        "node_run",
        {
            "node_name": "unit_node",
            "started_at": 1.0,
            "ended_at": 1.123,
            "duration_ms": 123,
            "output_summary": {"ok": True},
            "error": None,
        },
    )

    metrics = get_runtime_store().list_node_metrics("trace_metric_unit")
    assert metrics
    assert metrics[0]["node_name"] == "unit_node"


def test_prompt_registry_returns_versioned_specs() -> None:
    """关键 LLM prompt 必须有稳定版本和 schema 版本。"""

    spec = get_prompt_spec("intent_understanding")
    assert spec.prompt_version != "unversioned"
    assert spec.schema_name == "IntentUnderstandingOutput"


def test_trip_routes_can_delegate_to_services(monkeypatch) -> None:
    """路由层应能通过 service 完成规划，避免直接编排 DAG。"""

    called = {}

    def fake_plan(self, request):
        called["query"] = request.user_query
        from app.api.schemas.trip import TripPlanResponse

        return TripPlanResponse(
            response_text="ok",
            execution_status="done",
            selected_plan={},
            ranked_plans=[],
            errors=[],
            logs=[],
        )

    monkeypatch.setattr(TripPlanningService, "plan", fake_plan)
    from app.api.routes.trip import plan_trip

    response = plan_trip(TripPlanRequest(user_query="你好"))
    assert response.response_text == "ok"
    assert called["query"] == "你好"


def test_streaming_and_revision_services_expose_stream_methods() -> None:
    """流式和修正编排已经迁出 route，可作为 service 独立测试。"""

    assert callable(getattr(TripStreamingService(), "stream"))
    assert callable(getattr(TripRevisionService(), "stream"))

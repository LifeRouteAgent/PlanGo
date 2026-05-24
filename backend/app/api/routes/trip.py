from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from app.config import settings
from app.agents.availability_checker import availability_checker_node
from app.dag.langgraph_dag_config import life_route_graph
from app.agents.verifier import _issues_for_plan
from app.models.schemas import (
    AdjustPlanRequest,
    DataSourceStatusResponse,
    ExecutePlanRequest,
    RevisePlanRequest,
    TripPlanRequest,
    TripPlanResponse,
)
from app.agents.issue_utils import dedupe_issues
from app.agents.route_planner import (
    _build_route_segments,
    _build_timeline,
    _estimate_budget,
    _fit_stay_minutes,
    _fit_summary,
)
from app.services.amap_route_service import AmapRouteService
from app.services.calendar_service import build_plan_ics
from app.services.memory_service import MemoryService
from app.services.poi_repository import PoiRepository
from app.services.session_store import SessionStore
from app.services.tool_harness import ToolHarness
from app.services.trace_recorder import TraceRecorder, new_id, record_trace_event, set_trace_context
from app.state.plan_state import create_initial_state
from app.agents.planner_agent import planner_agent_node
from app.agents.poi_collector import poi_collector_node
from app.tools.poi_mix_recommend import poi_mix_recommend_node
from app.tools.poi_activity_recommend import poi_activity_recommend_node
from app.tools.poi_restaurant_recommend import poi_restaurant_recommend_node
from app.tools.poi_lifestyle_recommend import poi_lifestyle_recommend_node
from app.agents.route_planner import route_time_planner_node
from app.agents.verifier import verifier_node, verifier_route
from app.agents.ranker import ranker_node
from app.agents.response_generator import response_generator_node

router = APIRouter(prefix="/trip", tags=["trip"])


@router.get("/client-config")
def get_client_config() -> dict[str, str]:
    """返回前端运行所需的公开配置。

    前端高德 JS Key 必须下发到浏览器才能加载地图，因此这里统一从后端文件配置读取，
    避免前端继续依赖 Vite 环境变量。不要在这个接口返回数据库密码或 LLM Key。
    """

    return {
        "amap_key": settings.amap_api_key,
        "amap_security_js_code": "",
    }


@router.post("/plan", response_model=TripPlanResponse)
def plan_trip(request: TripPlanRequest) -> TripPlanResponse:
    """同步规划接口。

    这个接口保留给测试和非流式调用方使用；前端主流程优先调用 `/trip/plan/stream`。
    """

    session_store = SessionStore()
    memory = MemoryService()
    session_id = session_store.ensure_session_id(request.session_id)
    trace_id = request.trace_id or new_id("trace")
    run_id = request.run_id or new_id("run")
    set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
    memory.observe_user_query(request.user_query, user_id=session_id)
    user_profile = memory.enrich_user_profile({
        **request.user_profile,
        "last_query": request.user_query,
        "session_id": session_id,
        "user_id": session_id,
    })

    initial_state = create_initial_state(
        request.user_query,
        user_profile=user_profile,
        max_replanning_count=request.max_replanning_count,
        session_id=session_id,
        trace_id=trace_id,
        run_id=run_id,
    )
    recorder = TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=session_id)
    result = recorder.time_node(
        "life_route_graph.invoke",
        lambda: life_route_graph.invoke(initial_state),
        input_summary={"user_query": request.user_query},
    )
    response = _build_trip_response(result)
    session_store.save_turn(
        session_id=session_id,
        trace_id=trace_id,
        run_id=run_id,
        user_query=request.user_query,
        state=result,
        response=response.model_dump(),
    )
    return response


@router.post("/plan/stream")
def stream_plan_trip(request: TripPlanRequest) -> StreamingResponse:
    """SSE 流式规划接口。

    使用 LangGraph `stream(..., stream_mode="updates")` 按节点输出，而不是先完整
    `invoke()` 再切文本。这样前端能在 Intent、Collector、Skill、Ranker 等节点完成时
    立即收到状态；当 Response Generator 产出文本后，再逐段推送 `response_chunk`。
    """

    def event_stream() -> Iterator[str]:
        event_queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        session_store = SessionStore()
        memory = MemoryService()
        session_id = session_store.ensure_session_id(request.session_id)
        trace_id = request.trace_id or new_id("trace")
        run_id = request.run_id or new_id("run")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
        memory.observe_user_query(request.user_query, user_id=session_id)
        user_profile = memory.enrich_user_profile({
            **request.user_profile,
            "last_query": request.user_query,
            "session_id": session_id,
            "user_id": session_id,
        })
        recorder = TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=session_id)
        current_state = create_initial_state(
            request.user_query,
            user_profile=user_profile,
            max_replanning_count=request.max_replanning_count,
            session_id=session_id,
            trace_id=trace_id,
            run_id=run_id,
        )

        def run_graph() -> None:
            nonlocal current_state
            set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
            try:
                for update in life_route_graph.stream(current_state, stream_mode="updates"):
                    for node_name, patch in update.items():
                        recorder.record(
                            "node_run",
                            {
                                "node_name": node_name,
                                "started_at": time.time(),
                                "ended_at": time.time(),
                                "duration_ms": 0,
                                "input_summary": _summarize_patch(current_state),
                                "output_summary": _summarize_patch(patch),
                                "error": None,
                            },
                        )
                        current_state = _merge_stream_patch(current_state, patch)
                        latest_log = patch.get("logs", [])[-1] if patch.get("logs") else ""
                        event_queue.put((
                            "agent_thinking",
                            _build_agent_thinking_payload(node_name, patch, current_state),
                        ))
                        event_queue.put((
                            "agent_complete",
                            {
                                "agent": node_name,
                                "message": latest_log or f"{node_name} completed",
                                "summary": _summarize_patch(patch),
                            },
                        ))
                        event_queue.put((
                            "node_update",
                            {
                                "node": node_name,
                                "message": latest_log or f"{node_name} completed",
                            },
                        ))
                        for trace_event, trace_payload in _trace_events_for_node(
                            node_name,
                            patch,
                            current_state,
                        ):
                            event_queue.put((trace_event, trace_payload))
                        if node_name == "response_generator" and patch.get("response_text"):
                            for chunk in _chunk_text(str(patch["response_text"])):
                                event_queue.put(("response_chunk", {"delta": chunk}))
                event_queue.put(None)
            except Exception as exc:  # noqa: BLE001 - 流式接口需要把后台异常转成 SSE 事件。
                event_queue.put(("error", {"message": str(exc)}))
                event_queue.put(None)

        yield _sse_event(
            "status",
            {
                "stage": "start",
                "message": "已收到需求，开始理解意图并构建本地生活规划 DAG。",
            },
        )

        worker = threading.Thread(target=run_graph, daemon=True)
        worker.start()
        response_text_sent = False

        while True:
            try:
                queued = event_queue.get(timeout=0.8)
            except queue.Empty:
                yield _sse_event(
                    "progress",
                    {
                        "message": "规划仍在运行：正在等待大模型、数据库或路线节点返回。",
                    },
                )
                continue
            if queued is None:
                break
            event_name, payload = queued
            if event_name == "response_chunk":
                response_text_sent = True
                time.sleep(0.03)
            yield _sse_event(event_name, payload)

        response = _build_trip_response(current_state)

        yield _sse_event(
            "metadata",
            {
                "intent_type": response.intent_type,
                "answer_mode": response.answer_mode,
                "execution_status": response.execution_status,
                "need_clarification": response.need_clarification,
                "plan_count": len(response.ranked_plans),
                "session_id": response.session_id,
                "trace_id": response.trace_id,
                "run_id": response.run_id,
            },
        )

        if not response_text_sent:
            for chunk in _chunk_text(response.response_text):
                yield _sse_event("response_chunk", {"delta": chunk})
                time.sleep(0.03)

        session_store.save_turn(
            session_id=session_id,
            trace_id=trace_id,
            run_id=run_id,
            user_query=request.user_query,
            state=current_state,
            response=response.model_dump(),
        )
        yield _sse_event("final", response.model_dump())
        yield _sse_event("done", {"ok": True})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/plan/revise/stream")
def stream_revise_plan(request: RevisePlanRequest) -> StreamingResponse:
    """基于同一会话的上一版 PlanState 修正方案，而不是从空状态重新规划。"""

    def event_stream() -> Iterator[str]:
        session_store = SessionStore()
        memory = MemoryService()
        saved_session = session_store.load(request.session_id)
        if not saved_session or not isinstance(saved_session.get("latest_state"), dict):
            yield _sse_event("error", {"message": "没有找到可续跑的会话，请先生成一次方案。"})
            yield _sse_event("done", {"ok": False})
            return

        trace_id = new_id("trace")
        run_id = new_id("run")
        revision_id = new_id("rev")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=request.session_id)
        memory.observe_user_query(request.user_query, user_id=request.session_id)
        recorder = TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=request.session_id)
        current_state = _build_revision_state(
            saved_session["latest_state"],
            request.user_query,
            request.max_replanning_count,
            trace_id,
            run_id,
            revision_id,
        )
        current_state["user_profile"] = memory.enrich_user_profile({
            **current_state.get("user_profile", {}),
            "last_query": request.user_query,
            "session_id": request.session_id,
            "user_id": request.session_id,
        })
        _apply_revision_constraints(current_state, request.user_query)

        yield _sse_event(
            "status",
            {
                "stage": "revision",
                "session_id": request.session_id,
                "trace_id": trace_id,
                "run_id": run_id,
                "revision_id": revision_id,
                "message": "已读取上一版方案，正在基于新需求做局部/全局修正。",
            },
        )
        record_trace_event(
            "user_action",
            {
                "action": "revision_requested",
                "query": request.user_query,
                "selected_plan_id": request.selected_plan_id,
            },
        )

        try:
            current_state = _run_revision_pipeline(current_state, recorder, event_stream=True)
            response = _build_trip_response(current_state)
            session_store.save_turn(
                session_id=request.session_id,
                trace_id=trace_id,
                run_id=run_id,
                revision_id=revision_id,
                is_revision=True,
                user_query=request.user_query,
                state=current_state,
                response=response.model_dump(),
            )
            for chunk in _chunk_text(response.response_text):
                yield _sse_event("response_chunk", {"delta": chunk})
                time.sleep(0.03)
            yield _sse_event(
                "metadata",
                {
                    "session_id": response.session_id,
                    "trace_id": response.trace_id,
                    "run_id": response.run_id,
                    "revision_id": response.revision_id,
                    "is_revision": response.is_revision,
                    "plan_count": len(response.ranked_plans),
                },
            )
            yield _sse_event("final", response.model_dump())
            yield _sse_event("done", {"ok": True})
        except Exception as exc:  # noqa: BLE001 - 修正流需要把异常转成 SSE，避免前端一直等待。
            recorder.record("revision_error", {"error": str(exc)})
            yield _sse_event("error", {"message": str(exc)})
            yield _sse_event("done", {"ok": False})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/execute/stream")
def stream_execute_plan(request: ExecutePlanRequest) -> StreamingResponse:
    """Mock 执行方案流式接口。

    不调用真实预约、购票、打车 API，只根据方案内容生成可观察的执行步骤，并通过 SSE
    逐步返回 `running -> done` 状态。前端可以像真实执行一样逐个展示进度。
    """

    def event_stream() -> Iterator[str]:
        session_id = request.session_id or "execution_session"
        trace_id = request.trace_id or new_id("trace")
        run_id = request.run_id or new_id("run")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
        MemoryService().observe_selected_plan(request.plan, user_id=session_id)
        record_trace_event(
            "user_action",
            {
                "action": "plan_executed",
                "plan_id": request.plan.get("id"),
            },
        )
        harness = ToolHarness(
            name="execution.mock.build_steps",
            timeout_seconds=3,
            max_retries=1,
            fallback=lambda: [{
                "id": "execution_fallback",
                "type": "plan_ready",
                "title": "确认方案可执行",
                "description": "执行步骤生成失败，已降级为方案确认。",
            }],
        )
        harness_result = harness.run(_build_mock_execution_steps, request.plan)
        steps = harness_result.data if harness_result.success else []
        yield _sse_event(
            "execution_start",
            {
                "plan_id": request.plan.get("id"),
                "total_steps": len(steps),
                "session_id": session_id,
                "trace_id": trace_id,
                "run_id": run_id,
                "message": "开始模拟执行当前方案。",
            },
        )
        for step in steps:
            running = {**step, "status": "running"}
            yield _sse_event("execution_step", running)
            time.sleep(0.35)
            result_harness = ToolHarness(
                name=f"execution.mock.{step.get('type', 'step')}",
                timeout_seconds=2,
                max_retries=1,
                fallback=lambda current_step=step: "模拟执行降级完成。",
            )
            result = result_harness.run(_mock_execution_result, step)
            done = {
                **step,
                "status": "done",
                "result": result.data if result.success else "模拟执行完成。",
            }
            yield _sse_event("execution_step", done)
            if step.get("type") == "calendar_export":
                yield _sse_event(
                    "calendar_ready",
                    {
                        "plan_id": request.plan.get("id"),
                        "download_url": "/trip/calendar/ics",
                        "message": "日历文件已准备好，可下载后导入系统日历。",
                    },
                )
        yield _sse_event(
            "execution_done",
            {
                "status": "done",
                "message": "模拟执行完成，未调用真实第三方 API。",
            },
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/plan/adjust")
def adjust_plan(request: AdjustPlanRequest) -> dict[str, Any]:
    """局部替换某一站 POI。

    这是产品化调整能力的第一版：用户不满意某一站时，不必完整重跑 DAG，
    只按当前 POI 类别从数据库取替代候选，并替换 plan.items / timeline 中对应字段。
    """

    harness = ToolHarness(
        name="plan.adjust.replace_poi",
        timeout_seconds=6,
        max_retries=1,
        fallback=lambda: _fallback_adjust_response(request.plan, request.poi_id, request.prompt),
    )
    result = harness.run(_replace_plan_poi, request.plan, request.poi_id, request.prompt)
    if result.success and isinstance(result.data, dict):
        return result.data
    return _fallback_adjust_response(request.plan, request.poi_id, request.prompt)


@router.post("/calendar/ics")
def export_calendar_ics(request: ExecutePlanRequest) -> Response:
    """把当前方案导出为标准 ICS 日历文件，demo 阶段不接真实日历账号。"""

    session_id = request.session_id or "calendar_session"
    trace_id = request.trace_id or new_id("trace")
    run_id = request.run_id or new_id("run")
    set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
    record_trace_event(
        "user_action",
        {
            "action": "calendar_exported",
            "plan_id": request.plan.get("id"),
        },
    )
    if request.session_id:
        MemoryService().observe_selected_plan(request.plan, user_id=request.session_id)
    harness = ToolHarness(
        name="calendar.ics.export",
        timeout_seconds=3,
        max_retries=1,
        fallback=lambda: build_plan_ics(request.plan),
    )
    result = harness.run(build_plan_ics, request.plan)
    ics_text = result.data if result.success else build_plan_ics(request.plan)
    return Response(
        content=ics_text,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="liferoute-plan.ics"'},
    )


@router.get("/trace/{trace_id}")
def get_trace(trace_id: str) -> dict[str, Any]:
    """读取一次请求链路的 trace 事件，供调试页或 demo 复盘使用。"""

    return TraceRecorder.read(trace_id)


@router.delete("/memory")
def clear_memory(user_id: str | None = Query(default=None)) -> dict[str, Any]:
    """清空文件型长期记忆，并清理 Milvus 中对应用户/session 的向量记忆。"""

    MemoryService().clear(user_id=user_id)
    return {"ok": True}


@router.get("/memory/search")
def search_memory(
    q: str = Query(default="", description="检索关键词或自然语言问题"),
    limit: int = Query(default=5, ge=1, le=20),
    user_id: str = Query(default="default"),
) -> dict[str, Any]:
    """检索长期记忆；优先 Milvus 语义检索，不可用时回退文件关键词。"""

    memory = MemoryService()
    return {
        "query": q,
        "results": memory.semantic_search(q, limit=limit, user_id=user_id),
    }


@router.get("/memory/profile")
def get_memory_profile(user_id: str = Query(default="default")) -> dict[str, Any]:
    """返回当前用户画像、压缩上下文和向量存储状态。"""

    return MemoryService().profile_payload(user_id=user_id)


@router.post("/memory/rebuild-index")
def rebuild_memory_index(user_id: str = Query(default="default")) -> dict[str, Any]:
    """把文件型记忆重建到 Milvus，便于演示前手动补齐向量索引。"""

    return MemoryService().rebuild_vector_index(user_id=user_id)


@router.get("/memory/clusters")
def get_memory_clusters() -> dict[str, Any]:
    """返回 Milvus 用户画像向量的粗粒度聚类结果。"""

    return {"clusters": MemoryService().clusters()}


def _build_revision_state(
    previous_state: dict[str, Any],
    user_query: str,
    max_replanning_count: int,
    trace_id: str,
    run_id: str,
    revision_id: str,
) -> dict[str, Any]:
    """从上一轮完整 PlanState 克隆出可续跑状态，并保留原始意图和约束。"""

    state = dict(previous_state)
    state["user_query"] = user_query
    state["trace_id"] = trace_id
    state["run_id"] = run_id
    state["revision_id"] = revision_id
    state["is_revision"] = True
    state["max_replanning_count"] = max_replanning_count
    state["replanning_count"] = 0
    state["errors"] = []
    state["logs"] = [*state.get("logs", []), f"收到续跑修正需求：{user_query}"]
    state["candidate_plans"] = []
    state["verified_plans"] = []
    state["ranked_plans"] = []
    state["response_text"] = ""
    state["execution_status"] = "revision_running"
    return state


def _apply_revision_constraints(state: dict[str, Any], user_query: str) -> None:
    """把常见自然语言修正转成结构化约束，作为 Planner/Skill/Route 的输入。"""

    constraints = state.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    text = user_query.lower()
    avoid_tags = list(constraints.get("avoid_tags", []) or [])
    excluded_keywords = list(constraints.get("excluded_keywords", []) or [])
    if any(word in user_query for word in ["不要室外", "别室外", "太热", "下雨", "室内"]):
        constraints["indoor_preferred"] = True
        avoid_tags.extend(["室外", "公园", "露天", "户外"])
    if any(word in user_query for word in ["更便宜", "省钱", "便宜点", "预算低"]):
        constraints["budget_strategy"] = "lower_cost"
        constraints["price_preference"] = "low"
    if any(word in user_query for word in ["别太远", "近一点", "更近", "少走路"]):
        current_max = int(constraints.get("max_route_minutes", 45) or 45)
        constraints["max_route_minutes"] = min(current_max, 30)
        constraints["movement_policy"] = "low_movement"
    excluded_keywords.extend(_forbidden_terms(user_query))
    if "不要ktv" in text or "不要唱歌" in user_query:
        excluded_keywords.extend(["KTV", "唱歌"])
    constraints["avoid_tags"] = sorted({str(item) for item in avoid_tags if item})
    constraints["excluded_keywords"] = sorted({str(item) for item in excluded_keywords if item})
    state["constraints"] = constraints
    state["logs"] = [
        *state.get("logs", []),
        (
            f"已把修正需求转成约束：avoid_tags={constraints.get('avoid_tags', [])},"
            f" excluded_keywords={constraints.get('excluded_keywords', [])}"
        ),
    ]


def _run_revision_pipeline(
    state: dict[str, Any],
    recorder: TraceRecorder,
    *,
    event_stream: bool = False,
) -> dict[str, Any]:
    """跳过完整意图澄清，从 Planner 到 Response 重新生成可执行方案。"""

    del event_stream

    def run_node(node_name: str, node_fn) -> None:
        nonlocal state
        patch = recorder.time_node(
            node_name,
            lambda: node_fn(state),
            input_summary=_summarize_patch(state),
        )
        state = _merge_stream_patch(state, patch)
        for trace_event, trace_payload in _trace_events_for_node(node_name, patch, state):
            record_trace_event("product_progress", {"event": trace_event, **trace_payload})

    run_node("planner_agent", planner_agent_node)
    run_node("poi_collector", poi_collector_node)
    for skill_name, skill_fn in (
        ("poi_mix_recommend", poi_mix_recommend_node),
        ("poi_activity_recommend", poi_activity_recommend_node),
        ("poi_restaurant_recommend", poi_restaurant_recommend_node),
        ("poi_lifestyle_recommend", poi_lifestyle_recommend_node),
    ):
        run_node(skill_name, skill_fn)
    run_node("route_time_planner", route_time_planner_node)
    run_node("availability_checker", availability_checker_node)
    run_node("verifier", verifier_node)
    if verifier_route(state) == "replan":
        state["logs"] = [*state.get("logs", []), "修正方案未通过校验，按反馈重新收紧策略。"]
        run_node("planner_agent", planner_agent_node)
        run_node("poi_collector", poi_collector_node)
        for skill_name, skill_fn in (
            ("poi_mix_recommend", poi_mix_recommend_node),
            ("poi_activity_recommend", poi_activity_recommend_node),
            ("poi_restaurant_recommend", poi_restaurant_recommend_node),
            ("poi_lifestyle_recommend", poi_lifestyle_recommend_node),
        ):
            run_node(skill_name, skill_fn)
        run_node("route_time_planner", route_time_planner_node)
        run_node("availability_checker", availability_checker_node)
        run_node("verifier", verifier_node)
    run_node("ranker", ranker_node)
    run_node("response_generator", response_generator_node)
    return state


def _build_trip_response(result: dict[str, Any]) -> TripPlanResponse:
    """把内部 PlanState 裁剪成 API 对外响应结构。"""

    return TripPlanResponse(
        response_text=result.get("response_text", ""),
        execution_status=result.get("execution_status", "unknown"),
        intent_type=result.get("intent_type", ""),
        answer_mode=result.get("answer_mode", ""),
        need_clarification=result.get("need_clarification", False),
        missing_constraints=result.get("missing_constraints", []),
        clarify_question=result.get("clarify_question", ""),
        selected_plan=result.get("selected_plan", {}),
        ranked_plans=result.get("ranked_plans", []),
        errors=result.get("errors", []),
        logs=result.get("logs", []),
        session_id=result.get("session_id", ""),
        trace_id=result.get("trace_id", ""),
        run_id=result.get("run_id", ""),
        revision_id=result.get("revision_id", ""),
        is_revision=bool(result.get("is_revision", False)),
    )


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """按 Server-Sent Events 格式序列化事件。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _merge_stream_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """把 LangGraph stream update 合并成本轮最终状态。

    `stream_mode="updates"` 返回的是每个节点的局部 patch，不是完整状态。这里按
    PlanState 的 reducer 语义做最小合并：日志追加、候选 dict 合并、其他字段覆盖。
    """

    merged = dict(state)
    for key, value in patch.items():
        if key == "logs":
            merged[key] = [*merged.get(key, []), *value]
        elif key in {"candidate_pois", "recommended_pois"}:
            merged[key] = {**merged.get(key, {}), **value}
        else:
            merged[key] = value
    return merged


def _chunk_text(text: str, chunk_size: int = 18) -> Iterator[str]:
    """把完整响应切成小块，便于前端逐段渲染。"""

    if not text:
        return
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


def _trace_events_for_node(
    node_name: str,
    patch: dict[str, Any],
    current_state: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """把内部 DAG 节点输出转换成前端可展示的产品化进度事件。

    这里刻意不把完整 PlanState、SQL 结果或大模型原始输出透给前端，只保留用户能理解的
    阶段、结论和少量统计数据；这样既能展示“系统正在想什么”，也不会把页面变成调试控制台。
    """

    if node_name == "intent_router":
        return [(
            "intent_detected",
            {
                "stage": "understanding",
                "title": "理解需求",
                "message": _intent_trace_message(patch, current_state),
                "intent_type": current_state.get("intent_type", ""),
                "answer_mode": current_state.get("answer_mode", ""),
                "target_categories": _safe_list(current_state.get("target_categories")),
            },
        )]

    if node_name == "constraint_builder":
        constraints = current_state.get("constraints", {})
        return [(
            "constraints_built",
            {
                "stage": "constraints",
                "title": "整理条件",
                "message": "已整理人数、时间、预算、位置和移动范围，用于后续筛选。",
                "constraints": _public_constraints(
                    constraints if isinstance(constraints, dict) else {}
                ),
            },
        )]

    if node_name == "planner_agent":
        dag_plan = current_state.get("dag_plan", {})
        if not isinstance(dag_plan, dict):
            dag_plan = {}
        return [(
            "skill_selected",
            {
                "stage": "planning",
                "title": "选择规划策略",
                "message": _planner_trace_message(dag_plan),
                "planning_template": dag_plan.get("planning_template", ""),
                "enabled_skills": _safe_list(dag_plan.get("enabled_skills")),
                "collector_categories": _safe_list(dag_plan.get("collector_categories")),
                "slot_sequence": _safe_list(
                    dag_plan.get("slot_sequence") or dag_plan.get("required_slots")
                ),
                "movement_policy": dag_plan.get("movement_policy", ""),
                "candidate_strategy": dag_plan.get("candidate_strategy", ""),
            },
        )]

    if node_name == "poi_collector":
        counts = _count_mapping(current_state.get("candidate_pois", {}))
        return [(
            "poi_collected",
            {
                "stage": "collecting",
                "title": "检索本地地点",
                "message": f"已从本地数据库筛出 {sum(counts.values())} 个候选地点。",
                "candidate_counts": counts,
            },
        )]

    if node_name in {
        "poi_mix_recommend",
        "poi_activity_recommend",
        "poi_restaurant_recommend",
        "poi_lifestyle_recommend",
    }:
        counts = _count_mapping(patch.get("recommended_pois", {}))
        skill_label = _agent_title(node_name)
        return [(
            "skill_ranked",
            {
                "stage": "ranking_pois",
                "title": skill_label,
                "message": f"{skill_label} 已按偏好、预算、场景和风险重新排序。",
                "skill": node_name,
                "recommended_counts": counts,
            },
        )]

    if node_name == "route_time_planner":
        plans = current_state.get("candidate_plans", [])
        plan_count = len(plans) if isinstance(plans, list) else 0
        best_plan = plans[0] if plan_count and isinstance(plans[0], dict) else {}
        return [(
            "route_candidate_built",
            {
                "stage": "routing",
                "title": "生成动线",
                "message": f"已组合 {plan_count} 个带时间线的候选方案。",
                "candidate_plan_count": plan_count,
                "best_duration_minutes": best_plan.get("total_duration_minutes"),
                "best_route_minutes": best_plan.get("route_minutes"),
                "best_budget": best_plan.get("estimated_budget"),
            },
        )]

    if node_name == "verifier":
        issues = _public_issues(current_state.get("errors", []))
        verified = current_state.get("verified_plans", [])
        verified_count = len(verified) if isinstance(verified, list) else 0
        return [(
            "verification_issue",
            {
                "stage": "checking",
                "title": "校验可执行性",
                "message": (
                    f"发现 {len(issues)} 个需要注意的问题，正在尝试优化。"
                    if issues
                    else f"校验通过，保留 {verified_count} 个可执行方案。"
                ),
                "verified_count": verified_count,
                "issue_count": len(issues),
                "issues": issues,
            },
        )]

    if node_name == "ranker":
        ranked_plans = current_state.get("ranked_plans", [])
        ranked_count = len(ranked_plans) if isinstance(ranked_plans, list) else 0
        top_plan = ranked_plans[0] if ranked_count and isinstance(ranked_plans[0], dict) else {}
        return [(
            "plan_ranked",
            {
                "stage": "ranking_plans",
                "title": "方案排序",
                "message": f"已按偏好、距离、时间、预算综合排序出 {ranked_count} 个方案。",
                "ranked_count": ranked_count,
                "selected_plan_id": top_plan.get("id"),
                "top_plan_score": top_plan.get("plan_score"),
            },
        )]

    return []


def _intent_trace_message(patch: dict[str, Any], current_state: dict[str, Any]) -> str:
    """生成意图识别阶段的用户可读说明。"""

    intent_type = patch.get("intent_type", current_state.get("intent_type", ""))
    answer_mode = patch.get("answer_mode", current_state.get("answer_mode", ""))
    categories = _safe_list(current_state.get("target_categories"))
    if answer_mode == "simple_answer":
        return "判断这是一个简单问答，不需要进入完整行程规划。"
    if answer_mode == "category_recommend":
        return (
            "判断用户只需要单类推荐，"
            f"目标类别：{', '.join(str(item) for item in categories) or '待确认'}。"
        )
    return f"判断为 {intent_type or '本地生活'} 需求，需要生成可执行方案。"


def _planner_trace_message(dag_plan: dict[str, Any]) -> str:
    """生成 Planner 阶段的用户可读说明。"""

    template = dag_plan.get("planning_template") or "local_life_plan"
    skills = _safe_list(dag_plan.get("enabled_skills"))
    slots = _safe_list(dag_plan.get("slot_sequence") or dag_plan.get("required_slots"))
    return (
        f"采用 {template} 模板，启用 {len(skills)} 个推荐能力，"
        f"计划安排 {' -> '.join(str(item) for item in slots) if slots else '按需推荐'}。"
    )


def _public_constraints(constraints: dict[str, Any]) -> dict[str, Any]:
    """只暴露前端进度展示需要的约束字段。"""

    allowed_keys = {
        "city",
        "district",
        "start_area",
        "start_time",
        "end_time",
        "duration_hours",
        "duration_minutes",
        "budget",
        "people_count",
        "scenario",
        "preferences",
        "max_route_minutes",
        "transport_preference",
    }
    return {
        key: constraints.get(key)
        for key in allowed_keys
        if constraints.get(key) not in (None, "", [])
    }


def _public_issues(issues: Any) -> list[dict[str, Any]]:
    """把结构化 issue 压缩成前端展示所需字段。"""

    if not isinstance(issues, list):
        return []
    public: list[dict[str, Any]] = []
    for issue in issues[:8]:
        if not isinstance(issue, dict):
            continue
        public.append({
            "code": issue.get("code"),
            "severity": issue.get("severity"),
            "message": issue.get("message"),
            "suggestion": issue.get("suggestion"),
            "source": issue.get("source"),
            "target_plan_id": issue.get("target_plan_id"),
            "target_item_id": issue.get("target_item_id"),
        })
    return public


def _count_mapping(value: Any) -> dict[str, int]:
    """统计候选/推荐结果数量，避免前端消费完整 POI 列表。"""

    if not isinstance(value, dict):
        return {}
    return {str(key): len(items) for key, items in value.items() if isinstance(items, list)}


def _safe_list(value: Any) -> list[Any]:
    """把可选字段安全转换为列表，便于 SSE JSON 结构稳定。"""

    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return []


def _build_agent_thinking_payload(
    node_name: str,
    patch: dict[str, Any],
    current_state: dict[str, Any],
) -> dict[str, Any]:
    """把 LangGraph 节点 patch 转成前端可展示的 Thinking 事件。

    这里不暴露完整 PlanState，避免把大量 POI 和模型原始输出塞给前端；
    只给“节点做了什么、产出了什么、下一步可能是什么”。
    """

    return {
        "agent": node_name,
        "title": _agent_title(node_name),
        "message": _agent_message(node_name, patch, current_state),
        "summary": _summarize_patch(patch),
        "logs": patch.get("logs", [])[-3:] if isinstance(patch.get("logs"), list) else [],
    }


def _agent_title(node_name: str) -> str:
    """把内部节点名转成人能读懂的 Agent 名称。"""

    titles = {
        "intent_router": "意图路由",
        "intent_parser": "意图解析",
        "constraint_builder": "约束构建",
        "constraint_clarifier": "追问判断",
        "planner_agent": "规划模板",
        "poi_collector": "POI 检索",
        "poi_mix_recommend": "综合推荐 Skill",
        "poi_activity_recommend": "活动推荐 Skill",
        "poi_restaurant_recommend": "餐厅推荐 Skill",
        "poi_lifestyle_recommend": "生活方式 Skill",
        "post_skill_router": "推荐汇总",
        "route_time_planner": "路线时间规划",
        "availability_checker": "可用性检查",
        "verifier": "方案校验",
        "ranker": "方案排序",
        "response_generator": "响应生成",
        "user_confirm": "方案确认",
        "execution_agent": "执行准备",
    }
    return titles.get(node_name, "处理步骤")


def _agent_message(node_name: str, patch: dict[str, Any], current_state: dict[str, Any]) -> str:
    """生成 Thinking 面板的一句话解释。"""

    if node_name == "intent_router":
        return (
            f"判断为 {patch.get('intent_type', current_state.get('intent_type', '未知'))}，决定是否进入规划。"
        )
    if node_name == "intent_parser":
        return "提取场景、人数和偏好信息，准备整理规划条件。"
    if node_name == "constraint_builder":
        return "整理城市、时间、预算和路线约束。"
    if node_name == "constraint_clarifier":
        return (
            "当前信息还需补充，准备生成追问。"
            if patch.get("need_clarification")
            else "规划信息已满足要求，继续生成方案。"
        )
    if node_name == "planner_agent":
        return (
            "根据校验结果调整规划策略，重新组织候选方案。"
            if patch.get("replanning_count", 0) > 1
            else "生成规划模板，并确定候选地点检索策略。"
        )
    if node_name == "poi_collector":
        counts = {
            key: len(value)
            for key, value in patch.get("candidate_pois", {}).items()
            if isinstance(value, list)
        }
        return _format_poi_progress("从本地数据源召回", counts)
    if "recommend" in node_name:
        counts = {
            key: len(value)
            for key, value in patch.get("recommended_pois", {}).items()
            if isinstance(value, list)
        }
        return _format_poi_progress("按偏好、预算、场景和风险筛选", counts)
    if node_name == "post_skill_router":
        return "汇总并行推荐结果，准备进入下一步。"
    if node_name == "route_time_planner":
        return f"生成 {len(patch.get('candidate_plans', []))} 个带时间线的候选方案。"
    if node_name == "availability_checker":
        issues = patch.get("errors", [])
        return (
            f"发现 {len(issues)} 个可用性问题，交给方案校验处理。"
            if issues
            else "候选地点可用性检查完成。"
        )
    if node_name == "verifier":
        errors = patch.get("errors", [])
        return (
            "校验通过，进入排序。" if not errors else f"发现 {len(errors)} 个问题，准备回退或降级。"
        )
    if node_name == "ranker":
        return f"综合偏好、距离、时间、预算排序出 {len(patch.get('ranked_plans', []))} 个方案。"
    if node_name == "response_generator":
        return "把结构化方案转成用户可读文本，并补充方案操作。"
    if node_name == "user_confirm":
        return "方案已确认，进入执行模拟。"
    if node_name == "execution_agent":
        return (
            "已生成模拟执行结果。"
            if patch.get("execution_status") == "simulated"
            else "当前没有可执行方案，已跳过执行。"
        )
    return "当前处理步骤已完成。"


def _format_poi_progress(action: str, counts: dict[str, int]) -> str:
    """把内部 POI 分类计数转成面向用户的进度文案。"""

    total = sum(counts.values())
    if not counts:
        return f"{action}候选地点中。"
    if total == 0:
        return f"{action}完成，当前未筛出匹配地点。"

    category_labels = {
        "activity": "活动体验",
        "restaurant": "餐厅",
        "lifestyle": "生活方式",
        "mix": "综合",
        "poi_activity": "活动体验",
        "poi_restaurant": "餐厅",
        "poi_entertainment": "休闲娱乐",
        "poi_fitness": "运动健身",
        "poi_beauty": "美容养生",
        "poi_attraction": "景点",
        "poi_shopping": "购物",
    }
    detail = "、".join(
        f"{category_labels.get(category, '本地生活')} {count} 个"
        for category, count in counts.items()
        if count > 0
    )
    return f"{action}完成，得到{detail or f'{total} 个'}候选地点。"


def _summarize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """把节点输出压缩成小摘要，供前端展示和排障。"""

    return {
        "candidate_categories": (
            list(patch.get("candidate_pois", {}).keys())
            if isinstance(patch.get("candidate_pois"), dict)
            else []
        ),
        "recommended_categories": (
            list(patch.get("recommended_pois", {}).keys())
            if isinstance(patch.get("recommended_pois"), dict)
            else []
        ),
        "candidate_plan_count": (
            len(patch.get("candidate_plans", []))
            if isinstance(patch.get("candidate_plans"), list)
            else 0
        ),
        "ranked_plan_count": (
            len(patch.get("ranked_plans", [])) if isinstance(patch.get("ranked_plans"), list) else 0
        ),
        "error_count": len(patch.get("errors", [])) if isinstance(patch.get("errors"), list) else 0,
    }


def _build_mock_execution_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """根据方案内容生成 mock 执行步骤。

    - 行程里有餐厅：生成餐厅预约。
    - 活动/景点/娱乐：生成门票或场次锁定。
    - 有路线段：生成打车步骤。
    """

    steps: list[dict[str, Any]] = []
    items = plan.get("items", []) if isinstance(plan.get("items"), list) else []
    segments = (
        plan.get("route_segments", []) if isinstance(plan.get("route_segments"), list) else []
    )

    for item in items:
        category = str(item.get("category", ""))
        if category == "poi_restaurant":
            steps.append({
                "id": f"reserve_{item.get('id')}",
                "type": "restaurant_reservation",
                "title": f"预约餐厅：{item.get('name')}",
                "description": "模拟提交人数、时间和备注，等待商家确认。",
                "poi_id": item.get("id"),
                "poi_name": item.get("name"),
            })
        if category in {"poi_activity", "poi_attraction", "poi_entertainment"}:
            steps.append({
                "id": f"ticket_{item.get('id')}",
                "type": "ticket_purchase",
                "title": f"锁定门票/场次：{item.get('name')}",
                "description": "模拟查询余票、选择场次并生成待支付订单。",
                "poi_id": item.get("id"),
                "poi_name": item.get("name"),
            })

    for index, segment in enumerate(segments, start=1):
        steps.append({
            "id": f"ride_{index}",
            "type": "ride_hailing",
            "title": f"叫车：{segment.get('from')} → {segment.get('to')}",
            "description": (
                f"模拟预估 {segment.get('duration_minutes', 0)} 分钟，约"
                f" {segment.get('distance_km', 0)} km。"
            ),
            "from": segment.get("from"),
            "to": segment.get("to"),
            "transport_mode": segment.get("transport_mode"),
        })

    steps.append({
        "id": "calendar_export",
        "type": "calendar_export",
        "title": "生成日历文件",
        "description": "把确认后的时间线导出为标准 ICS，方便导入系统日历。",
    })

    if not steps:
        steps.append({
            "id": "share_only",
            "type": "plan_ready",
            "title": "确认方案可执行",
            "description": "当前方案没有需要 mock 的预约、购票或打车步骤。",
        })
    return steps


def _mock_execution_result(step: dict[str, Any]) -> str:
    """为 mock 执行步骤生成完成文案。"""

    step_type = step.get("type")
    if step_type == "restaurant_reservation":
        return "已生成模拟预约单，状态：待商家确认。"
    if step_type == "ticket_purchase":
        return "已生成模拟票务订单，状态：待支付。"
    if step_type == "ride_hailing":
        return "已生成模拟叫车单，状态：等待司机接单。"
    if step_type == "calendar_export":
        return "已生成可导入系统日历的 ICS 文件。"
    return "已完成模拟确认。"


def _replace_plan_poi(plan: dict[str, Any], poi_id: str, prompt: str) -> dict[str, Any]:
    """按类别替换方案中的单个 POI。

    目前采用确定性策略：
    - 找到原 POI 的 category。
    - 从本地数据库同类别召回候选。
    - 排除原 POI，按用户调整 prompt 做轻量打分。
    - 替换 items 和 timeline 中对应地点字段。
    """

    items = plan.get("items", []) if isinstance(plan.get("items"), list) else []
    old_item = next((item for item in items if str(item.get("id")) == str(poi_id)), None)
    if not old_item:
        return _fallback_adjust_response(plan, poi_id, prompt, "没有找到要替换的地点。")

    category = str(old_item.get("category") or "")
    candidates = (
        PoiRepository(limit_per_category=50).fetch_by_categories([category]).get(category, [])
    )
    candidate_dicts = [
        dict(candidate) for candidate in candidates if str(candidate.get("id")) != str(poi_id)
    ]
    if not candidate_dicts:
        return _fallback_adjust_response(plan, poi_id, prompt, "当前类别没有可替换候选。")

    replacement = _pick_replacement(candidate_dicts, prompt, old_item)
    adjusted_plan = _apply_replacement(plan, old_item, replacement, prompt)
    adjusted_plan = _recalculate_adjusted_plan(adjusted_plan)
    return {
        "success": True,
        "plan": adjusted_plan,
        "old_poi": old_item,
        "new_poi": replacement,
        "issues": adjusted_plan.get("issues", []),
        "message": f"已将「{old_item.get('name')}」替换为「{replacement.get('name')}」。",
    }


def _pick_replacement(
    candidates: list[dict[str, Any]],
    prompt: str,
    old_item: dict[str, Any],
) -> dict[str, Any]:
    """根据调整意图选择替代 POI。"""

    prompt_text = prompt.lower()

    def score(candidate: dict[str, Any]) -> float:
        value = float(candidate.get("rating", 0) or 0)
        tags = " ".join(str(tag) for tag in candidate.get("tags", []))
        name = str(candidate.get("name", ""))
        subcategory = str(candidate.get("subcategory", ""))
        joined = f"{name} {subcategory} {tags}"
        if "室内" in prompt and any(
            word in joined for word in ["室内", "商场", "影院", "ktv", "KTV", "棋牌", "桌游"]
        ):
            value += 1.5
        if "不要火锅" in prompt and "火锅" in joined:
            value -= 5
        if "便宜" in prompt or "省钱" in prompt or "预算" in prompt:
            if str(candidate.get("price_level")) == "low":
                value += 1.2
            if str(candidate.get("price_level")) == "high":
                value -= 1.2
        if "近" in prompt_text or "near" in prompt_text:
            value += max(0, 1 - _rough_distance(old_item, candidate) / 10)
        return value

    return sorted(candidates, key=score, reverse=True)[0]


def _apply_replacement(
    plan: dict[str, Any],
    old_item: dict[str, Any],
    replacement: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    """把替换结果写回方案结构。"""

    adjusted = dict(plan)
    old_id = str(old_item.get("id"))
    replacement_item = {
        **replacement,
        "recommendation_reason": f"根据“{prompt}”替换，保留原类别但更贴近当前调整方向。",
        "option_prompts": (
            replacement.get("option_prompts") or ["再近一点", "换成室内", "换个更省钱的"]
        ),
    }
    adjusted["items"] = [
        replacement_item if str(item.get("id")) == old_id else item
        for item in adjusted.get("items", [])
    ]

    timeline = []
    for entry in adjusted.get("timeline", []) if isinstance(adjusted.get("timeline"), list) else []:
        if str(entry.get("poi_id")) == old_id:
            timeline.append({
                **entry,
                "poi_id": replacement_item.get("id"),
                "title": replacement_item.get("name"),
                "address": replacement_item.get("address"),
            })
        else:
            timeline.append(entry)
    adjusted["timeline"] = timeline
    adjusted["title"] = f"{adjusted.get('title', '方案')}（已局部调整）"
    adjusted["recommendation_reason"] = f"已按“{prompt}”替换单站，其他安排保持不变。"
    return adjusted


def _rough_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """粗略距离，用于局部替换排序；真实路线仍由 Route Planner/高德阶段负责。"""

    try:
        return (
            abs(float(a.get("lat", 0)) - float(b.get("lat", 0))) * 111
            + abs(float(a.get("lon", 0)) - float(b.get("lon", 0))) * 85
        )
    except TypeError, ValueError:
        return 99


def _pick_replacement(
    candidates: list[dict[str, Any]],
    prompt: str,
    old_item: dict[str, Any],
) -> dict[str, Any]:
    """根据局部调整意图选择替代 POI。

    这里覆盖上方旧实现，保留同名函数是为了不改动 `/plan/adjust` 的调用点。
    支持“更近、室内、更省钱、时间短一点、不要 X”等产品化调整选项。
    """

    prompt_text = prompt.lower()
    forbidden_terms = _forbidden_terms(prompt)

    def score(candidate: dict[str, Any]) -> float:
        value = float(candidate.get("rating", 0) or 0)
        tags = " ".join(str(tag) for tag in candidate.get("tags", []))
        joined = f"{candidate.get('name', '')} {candidate.get('subcategory', '')} {tags}"
        distance = _rough_distance(old_item, candidate)
        if any(term and term in joined for term in forbidden_terms):
            value -= 8
        if "室内" in prompt and any(
            word in joined
            for word in ["室内", "商场", "影院", "电影", "ktv", "KTV", "棋牌", "桌游"]
        ):
            value += 1.5
        if "不要火锅" in prompt and "火锅" in joined:
            value -= 5
        if "便宜" in prompt or "省钱" in prompt or "预算" in prompt:
            if str(candidate.get("price_level")) == "low":
                value += 1.2
            if str(candidate.get("price_level")) == "high":
                value -= 1.2
        if "近" in prompt_text or "near" in prompt_text:
            value += max(0, 2 - distance / 5)
        if "时间短" in prompt or "短一点" in prompt:
            value -= distance / 8
        return value

    return sorted(candidates, key=score, reverse=True)[0]


def _apply_replacement(
    plan: dict[str, Any],
    old_item: dict[str, Any],
    replacement: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    """把替换结果写回方案，并保留 slot_type 供后续重算时间线。"""

    adjusted = dict(plan)
    old_id = str(old_item.get("id"))
    old_slot_type = _slot_type_for_item(plan, old_id)
    replacement_item = {
        **replacement,
        "slot_type": old_slot_type,
        "recommendation_reason": f"根据“{prompt}”替换，保留原槽位类型并优先满足当前调整方向。",
        "option_prompts": (
            replacement.get("option_prompts") or ["再近一点", "换成室内", "换个更省钱的"]
        ),
    }
    adjusted["items"] = [
        replacement_item if str(item.get("id")) == old_id else item
        for item in adjusted.get("items", [])
    ]
    adjusted["title"] = f"{adjusted.get('title', '方案')}（已局部调整）"
    adjusted["recommendation_reason"] = f"已按“{prompt}”替换单站，并重新计算路线、时间和预算。"
    return adjusted


def _recalculate_adjusted_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """局部替换后重算路线、时间线、预算和 Verifier 结果。"""

    adjusted = dict(plan)
    items = [dict(item) for item in adjusted.get("items", []) if isinstance(item, dict)]
    duration_limit = _infer_duration_limit(adjusted)
    budget_limit = _infer_budget_limit(adjusted)
    start_time = _infer_start_time(adjusted)
    # 局部替换是用户交互链路，必须快；这里强制用 Haversine fallback，完整规划再走高德路线增强。
    route_segments = _build_route_segments(items, AmapRouteService(api_key=""))
    route_minutes = sum(int(segment.get("duration_minutes", 0) or 0) for segment in route_segments)
    stay_minutes = _fit_stay_minutes(items, route_minutes, duration_limit)
    total_duration = sum(stay_minutes) + route_minutes
    estimated_budget = _estimate_budget(items)
    timeline = _build_timeline(items, route_segments, start_time, stay_minutes)
    issues = dedupe_issues(
        _issues_for_plan(
            {
                **adjusted,
                "items": items,
                "route_segments": route_segments,
                "route_minutes": route_minutes,
                "total_duration_minutes": total_duration,
                "estimated_budget": estimated_budget,
            },
            max_route_minutes=45,
            duration_limit=duration_limit,
            budget=budget_limit,
        )
    )
    return {
        **adjusted,
        "items": items,
        "timeline": timeline,
        "route_segments": route_segments,
        "total_distance_km": round(
            sum(float(s.get("distance_km", 0) or 0) for s in route_segments), 2
        ),
        "route_minutes": route_minutes,
        "total_duration_minutes": total_duration,
        "estimated_budget": estimated_budget,
        "fit_summary": _fit_summary(
            items=items,
            route_minutes=route_minutes,
            total_duration=total_duration,
            duration_limit=duration_limit,
            estimated_budget=estimated_budget,
            budget=budget_limit,
        ),
        "issues": issues,
        "verified": not any(issue.get("severity") == "error" for issue in issues),
    }


def _slot_type_for_item(plan: dict[str, Any], poi_id: str) -> str:
    """从原 timeline 中找回被替换 POI 的 slot_type。"""

    for entry in plan.get("timeline", []) if isinstance(plan.get("timeline"), list) else []:
        if str(entry.get("poi_id")) == str(poi_id):
            return str(entry.get("slot_type") or "poi")
    return "poi"


def _infer_duration_limit(plan: dict[str, Any]) -> int:
    """局部调整时沿用原方案时间窗口，缺失时默认 4 小时。"""

    value = int(plan.get("duration_limit") or plan.get("time_budget") or 0)
    if value > 0:
        return value
    return max(240, int(plan.get("total_duration_minutes", 0) or 0))


def _infer_budget_limit(plan: dict[str, Any]) -> int:
    """局部调整时沿用原预算，缺失时默认不低于当前估算预算。"""

    value = int(plan.get("budget") or plan.get("budget_limit") or 0)
    if value > 0:
        return value
    return max(600, int(plan.get("estimated_budget", 0) or 0))


def _infer_start_time(plan: dict[str, Any]) -> str:
    """从原时间线推断开始时间，缺失时使用下午 2 点。"""

    timeline = plan.get("timeline", [])
    if isinstance(timeline, list) and timeline:
        return str(timeline[0].get("start_time") or "14:00")
    return "14:00"


def _forbidden_terms(prompt: str) -> list[str]:
    """从用户调整文案里提取“不要 X”的轻量排除词。"""

    terms: list[str] = []
    for marker in ("不要", "不想要", "别要", "换掉"):
        if marker not in prompt:
            continue
        tail = prompt.split(marker, 1)[1].strip()
        if tail:
            terms.append(tail[:8])
    return terms


def _fallback_adjust_response(
    plan: dict[str, Any],
    poi_id: str,
    prompt: str,
    message: str = "局部替换失败，已保留原方案。",
) -> dict[str, Any]:
    """局部替换失败时的稳定返回。"""

    return {
        "success": False,
        "plan": plan,
        "old_poi": {"id": poi_id},
        "new_poi": None,
        "message": f"{message} 调整意图：{prompt}",
    }


@router.get("/data-source", response_model=DataSourceStatusResponse)
def data_source_status() -> DataSourceStatusResponse:
    """返回当前 POI 数据源状态。

    前端和人工 review 可以用这个接口确认当前是否真的在读取本地 MySQL，
    而不是因为连接失败悄悄降级到 Mock。
    """

    if not settings.use_database:
        return DataSourceStatusResponse(
            enabled=False,
            source="mock",
            database_name=settings.database_name,
        )

    try:
        return DataSourceStatusResponse(
            enabled=True,
            source="mysql",
            database_name=settings.database_name,
            table_counts=PoiRepository().table_counts(),
        )
    except Exception as exc:  # noqa: BLE001 - 健康检查接口需要把数据库异常转成可读状态
        return DataSourceStatusResponse(
            enabled=False,
            source="mysql_error",
            database_name=settings.database_name,
            error=str(exc),
        )

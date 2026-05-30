from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any

from app.agents.availability_checker import availability_checker_node
from app.agents.planner_agent import planner_agent_node
from app.agents.poi_collector import poi_collector_node
from app.agents.ranker import ranker_node
from app.agents.response_generator import response_generator_node
from app.agents.route_planner import route_time_planner_node
from app.agents.verifier import verifier_node, verifier_route
from app.agents.llm_critic import llm_critic_node
from app.dag.langgraph_dag_config import life_route_graph
from app.models.schemas import TripPlanRequest, TripPlanResponse
from app.models.schemas import RevisePlanRequest
from app.services.amap_weather_service import AmapWeatherService
from app.services.checkpoint_store import CheckpointStore, TaskStatus
from app.services.llm_semantic_extractor import extract_revision_constraints
from app.services.memory_service import MemoryService
from app.services.policy_config import policy_config
from app.services.runtime_store import get_runtime_store
from app.services.session_store import SessionStore
from app.services.trace_recorder import TraceRecorder, new_id, record_trace_event, set_trace_context, summarize_state_patch
from app.state.plan_state import create_initial_state
from app.tools.poi_activity_recommend import poi_activity_recommend_node
from app.tools.poi_lifestyle_recommend import poi_lifestyle_recommend_node
from app.tools.poi_mix_recommend import poi_mix_recommend_node
from app.tools.poi_restaurant_recommend import poi_restaurant_recommend_node


class TripPlanningService:
    """非流式规划编排服务。

    这里承接原 `trip.py` 中同步接口的业务编排，路由层只负责请求响应转换。
    流式接口仍保留在路由内，避免一次性大改破坏前端 SSE 兼容性。
    """

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
        task = self.checkpoint.create(
            session_id=session_id,
            user_id=session_id,
            trace_id=trace_id,
        )
        task_id = str(task["task_id"])
        saved_session = self.session_store.load(session_id)
        effective_query = effective_query_for_request(saved_session, request.user_query)
        self.memory.observe_user_query(request.user_query, user_id=session_id)
        user_profile = self.memory.enrich_user_profile({
            **request.user_profile,
            "last_query": effective_query,
            "session_id": session_id,
            "user_id": session_id,
        })
        initial_state = create_initial_state(
            effective_query,
            user_profile=user_profile,
            max_replanning_count=request.max_replanning_count,
            session_id=session_id,
            trace_id=trace_id,
            run_id=run_id,
            task_id=task_id,
        )
        self.checkpoint.save_from_plan_state(
            initial_state,
            status=TaskStatus.CREATED,
            task_id=task_id,
        )
        if effective_query != request.user_query:
            initial_state["logs"] = [
                *initial_state.get("logs", []),
                (
                    "Clarification Follow-up: merged user reply into previous pending request:"
                    f" {request.user_query}"
                ),
            ]
        recorder = TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=session_id)
        result = recorder.time_node(
            "life_route_graph.invoke",
            lambda: life_route_graph.invoke(initial_state),
            input_summary={"user_query": request.user_query},
        )
        self.checkpoint.save_from_plan_state(
            result,
            status=checkpoint_status_from_state(result),
            task_id=task_id,
        )
        response = build_trip_response(result)
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
    """流式规划服务。

    路由层只负责把这个 iterator 包进 `StreamingResponse`。这里统一处理
    session、memory、checkpoint、LangGraph stream、SSE 事件和节点耗时指标。
    """

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
        event_queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        session_id = self.session_store.ensure_session_id(request.session_id)
        trace_id = request.trace_id or new_id("trace")
        run_id = request.run_id or new_id("run")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
        task = self.checkpoint.create(session_id=session_id, user_id=session_id, trace_id=trace_id)
        task_id = str(task["task_id"])
        saved_session = self.session_store.load(session_id)
        effective_query = effective_query_for_request(saved_session, request.user_query)
        is_clarification_followup = effective_query != request.user_query
        self.memory.observe_user_query(request.user_query, user_id=session_id)
        user_profile = self.memory.enrich_user_profile({
            **request.user_profile,
            "last_query": effective_query,
            "session_id": session_id,
            "user_id": session_id,
        })
        recorder = TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=session_id)
        current_state = create_initial_state(
            effective_query,
            user_profile=user_profile,
            max_replanning_count=request.max_replanning_count,
            session_id=session_id,
            trace_id=trace_id,
            run_id=run_id,
            task_id=task_id,
        )
        self.checkpoint.save_from_plan_state(current_state, status=TaskStatus.CREATED, task_id=task_id)
        if is_clarification_followup:
            current_state["logs"] = [
                *current_state.get("logs", []),
                (
                    "Clarification Follow-up: merged user reply into previous pending request:"
                    f" {request.user_query}"
                ),
            ]

        def run_graph() -> None:
            nonlocal current_state
            set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
            last_update_at = time.time()
            try:
                for update in life_route_graph.stream(current_state, stream_mode="updates"):
                    for node_name, patch in update.items():
                        now = time.time()
                        duration_ms = max(0, int((now - last_update_at) * 1000))
                        last_update_at = now
                        recorder.record(
                            "node_run",
                            {
                                "node_name": node_name,
                                "started_at": now - duration_ms / 1000,
                                "ended_at": now,
                                "duration_ms": duration_ms,
                                "input_summary": summarize_state_patch(current_state),
                                "output_summary": summarize_state_patch(patch),
                                "error": None,
                            },
                        )
                        current_state = merge_state_patch(current_state, patch)
                        self.checkpoint.save_from_plan_state(
                            current_state,
                            status=checkpoint_status_for_node(node_name, current_state),
                            task_id=task_id,
                        )
                        latest_log = patch.get("logs", [])[-1] if patch.get("logs") else ""
                        event_queue.put((
                            "agent_thinking",
                            build_agent_thinking_payload(node_name, patch, current_state),
                        ))
                        event_queue.put((
                            "node_update",
                            {
                                "node": node_name,
                                "message": latest_log or f"{node_name} completed",
                                "duration_ms": duration_ms,
                            },
                        ))
                        if node_name == "response_generator" and patch.get("response_text"):
                            for chunk in chunk_text(str(patch["response_text"])):
                                event_queue.put(("response_chunk", {"delta": chunk}))
                event_queue.put(None)
            except Exception as exc:  # noqa: BLE001
                recorder.record(
                    "node_run",
                    {
                        "node_name": "life_route_graph.stream",
                        "started_at": time.time(),
                        "ended_at": time.time(),
                        "duration_ms": 0,
                        "input_summary": summarize_state_patch(current_state),
                        "output_summary": {},
                        "error": str(exc),
                    },
                )
                event_queue.put(("error", {"message": str(exc)}))
                event_queue.put(None)

        yield sse_event(
            "status",
            {
                "stage": "clarification_followup" if is_clarification_followup else "start",
                "message": (
                    "已接上上一轮追问，把你的补充信息合并进原始规划需求。"
                    if is_clarification_followup
                    else "已收到需求，开始理解意图并构建本地生活规划 DAG。"
                ),
            },
        )

        worker = threading.Thread(target=run_graph, daemon=True)
        worker.start()
        response_text_sent = False
        while True:
            try:
                queued = event_queue.get(timeout=0.8)
            except queue.Empty:
                yield sse_event(
                    "progress",
                    {"message": "规划仍在运行：正在等待大模型、数据库或路线节点返回。"},
                )
                continue
            if queued is None:
                break
            event_name, payload = queued
            if event_name == "response_chunk":
                response_text_sent = True
                time.sleep(0.03)
            yield sse_event(event_name, payload)

        response = build_trip_response(current_state)
        yield sse_event(
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
                "task_id": response.task_id,
            },
        )
        if not response_text_sent:
            for chunk in chunk_text(response.response_text):
                yield sse_event("response_chunk", {"delta": chunk})
                time.sleep(0.03)
        self.session_store.save_turn(
            session_id=session_id,
            trace_id=trace_id,
            run_id=run_id,
            user_query=request.user_query,
            state=current_state,
            response=response.model_dump(),
        )
        yield sse_event("final", response.model_dump())
        yield sse_event("done", {"ok": True})


class TripRevisionService:
    """需求修正流式服务。

    它基于同一 session 的上一版 PlanState 修正方案，而不是从空状态重新规划。
    """

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
        saved_session = self.session_store.load(request.session_id)
        if not saved_session or not isinstance(saved_session.get("latest_state"), dict):
            yield sse_event("error", {"message": "没有找到可续跑的会话，请先生成一次方案。"})
            yield sse_event("done", {"ok": False})
            return
        trace_id = new_id("trace")
        run_id = new_id("run")
        revision_id = new_id("rev")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=request.session_id)
        task = self.checkpoint.create(
            session_id=request.session_id,
            user_id=request.session_id,
            trace_id=trace_id,
        )
        task_id = str(task["task_id"])
        self.memory.observe_user_query(request.user_query, user_id=request.session_id)
        recorder = TraceRecorder(trace_id=trace_id, run_id=run_id, session_id=request.session_id)
        current_state = build_revision_state(
            saved_session["latest_state"],
            request.user_query,
            request.max_replanning_count,
            trace_id,
            run_id,
            revision_id,
        )
        current_state["task_id"] = task_id
        current_state["user_profile"] = self.memory.enrich_user_profile({
            **current_state.get("user_profile", {}),
            "last_query": request.user_query,
            "session_id": request.session_id,
            "user_id": request.session_id,
        })
        apply_revision_constraints(current_state, request.user_query)
        self.memory.observe_revision(
            request.user_query,
            current_state.get("constraints", {}),
            user_id=request.session_id,
        )
        self.checkpoint.save_from_plan_state(current_state, status=TaskStatus.CREATED, task_id=task_id)
        yield sse_event(
            "status",
            {
                "stage": "revision",
                "session_id": request.session_id,
                "trace_id": trace_id,
                "run_id": run_id,
                "revision_id": revision_id,
                "task_id": task_id,
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
            current_state = run_revision_pipeline(current_state, recorder)
            self.checkpoint.save_from_plan_state(
                current_state,
                status=checkpoint_status_from_state(current_state),
                task_id=task_id,
            )
            response = build_trip_response(current_state)
            self.session_store.save_turn(
                session_id=request.session_id,
                trace_id=trace_id,
                run_id=run_id,
                revision_id=revision_id,
                is_revision=True,
                user_query=request.user_query,
                state=current_state,
                response=response.model_dump(),
            )
            for chunk in chunk_text(response.response_text):
                yield sse_event("response_chunk", {"delta": chunk})
                time.sleep(0.03)
            yield sse_event(
                "metadata",
                {
                    "session_id": response.session_id,
                    "trace_id": response.trace_id,
                    "run_id": response.run_id,
                    "revision_id": response.revision_id,
                    "is_revision": response.is_revision,
                    "task_id": response.task_id,
                    "plan_count": len(response.ranked_plans),
                },
            )
            yield sse_event("final", response.model_dump())
            yield sse_event("done", {"ok": True})
        except Exception as exc:  # noqa: BLE001
            recorder.record("revision_error", {"error": str(exc)})
            yield sse_event("error", {"message": str(exc)})
            yield sse_event("done", {"ok": False})


class TripExecutionService:
    """执行 mock 的策略辅助服务。"""

    def risk_level_for_step(self, step: dict[str, Any]) -> int:
        action_type = str(step.get("type") or step.get("action_type") or "")
        return policy_config.risk_policy.risk_level_for(action_type, default=1)

    def validated_item_ids(self, plan: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for item in plan.get("items", []) if isinstance(plan.get("items"), list) else []:
            item_id = str(item.get("id") or "")
            if item_id:
                result.append(item_id)
        return result


class TaskRecoveryService:
    """任务 checkpoint 查询和恢复决策服务。"""

    def __init__(self, checkpoint: CheckpointStore | None = None) -> None:
        self.checkpoint = checkpoint or CheckpointStore()

    def task_payload(self, task_id: str) -> dict[str, Any]:
        task = self.checkpoint.load(task_id)
        return {"ok": bool(task), "task": task}

    def resume_decision(self, task_id: str) -> dict[str, Any]:
        return self.checkpoint.resume(task_id)

    def runtime_summary(self) -> dict[str, Any]:
        """聚合本地运行工件，给评测和观测面板使用。"""

        runtime = get_runtime_store()
        tasks = runtime.list_tasks()
        node_metrics = runtime.list_node_metrics()
        statuses: dict[str, int] = {}
        action_statuses: dict[str, int] = {}
        for task in tasks:
            status = str(task.get("status") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            for action in task.get("booking_actions", []) or []:
                action_status = str(action.get("status") or "unknown")
                action_statuses[action_status] = action_statuses.get(action_status, 0) + 1
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "task_count": len(tasks),
            "trace_count": len({metric.get("trace_id") for metric in node_metrics if metric.get("trace_id")}),
            "status_counts": statuses,
            "action_status_counts": action_statuses,
            "node_metric_count": len(node_metrics),
            "slowest_nodes": node_metrics[:10],
            "recoverable_task_count": len(self.checkpoint.recoverable_tasks()),
        }

    def node_metrics(self, trace_id: str | None = None) -> dict[str, Any]:
        metrics = get_runtime_store().list_node_metrics(trace_id)
        return {
            "trace_id": trace_id or "",
            "count": len(metrics),
            "metrics": metrics,
        }

    def runtime_health(self) -> dict[str, Any]:
        return get_runtime_store().health()


def effective_query_for_request(
    saved_session: dict[str, Any] | None,
    current_query: str,
) -> str:
    """把澄清追问后的短回答合并回上一轮待补全需求。"""

    previous_state = latest_pending_clarification_state(saved_session)
    if not previous_state:
        return current_query
    previous_query = str(previous_state.get("user_query") or "").strip()
    reply = current_query.strip()
    if not previous_query or not reply:
        return current_query
    return f"{previous_query}\n补充信息：{reply}"


def latest_pending_clarification_state(
    saved_session: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """读取上一轮是否处于等待澄清状态。"""

    if not isinstance(saved_session, dict):
        return None
    latest_state = saved_session.get("latest_state")
    latest_response = saved_session.get("latest_response")
    if not isinstance(latest_state, dict):
        return None
    state_waiting = bool(latest_state.get("need_clarification"))
    response_waiting = isinstance(latest_response, dict) and bool(
        latest_response.get("need_clarification")
    )
    if state_waiting or response_waiting:
        return latest_state
    return None


def build_trip_response(result: dict[str, Any]) -> TripPlanResponse:
    """把内部 PlanState 裁剪成 API 对外响应结构。"""

    result = attach_weather_to_result(result)
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
        task_id=result.get("task_id", ""),
    )


def attach_weather_to_result(result: dict[str, Any]) -> dict[str, Any]:
    """把高德实时天气挂到最终方案，供前端天气卡片直接展示。"""

    if not result.get("ranked_plans") and not result.get("selected_plan"):
        return result
    weather = AmapWeatherService().current_weather(
        str(result.get("constraints", {}).get("city") or "北京")
    )
    ranked_plans = [
        {**plan, "weather": weather}
        for plan in result.get("ranked_plans", [])
        if isinstance(plan, dict)
    ]
    selected_plan = dict(result.get("selected_plan", {}) or {})
    if selected_plan:
        selected_plan["weather"] = weather
    return {
        **result,
        "ranked_plans": ranked_plans,
        "selected_plan": selected_plan,
        "weather": weather,
    }


def checkpoint_status_from_state(state: dict[str, Any]) -> TaskStatus:
    """根据 PlanState 的当前结果推断 checkpoint 阶段。"""

    if state.get("selected_plan") or state.get("ranked_plans"):
        return TaskStatus.PLAN_VALIDATED
    if state.get("candidate_plans"):
        return TaskStatus.PLAN_GENERATED
    if state.get("candidate_pois"):
        return TaskStatus.CANDIDATES_RECALLED
    if state.get("intent_type"):
        return TaskStatus.INTENT_PARSED
    return TaskStatus.CREATED


def sse_event(event: str, data: dict[str, Any]) -> str:
    """按 Server-Sent Events 格式序列化事件。"""

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def merge_state_patch(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """按 PlanState reducer 语义合并 LangGraph stream patch。"""

    merged = dict(state)
    for key, value in patch.items():
        if key == "logs":
            merged[key] = [*merged.get(key, []), *value]
        elif key in {"candidate_pois", "recommended_pois"}:
            merged[key] = {**merged.get(key, {}), **value}
        elif key in {"tool_evidence", "booking_actions"}:
            merged[key] = [*merged.get(key, []), *value]
        else:
            merged[key] = value
    return merged


def chunk_text(text: str, chunk_size: int = 18) -> Iterator[str]:
    """把完整响应切成小块，便于前端逐段渲染。"""

    for index in range(0, len(text or ""), chunk_size):
        yield text[index : index + chunk_size]


def checkpoint_status_for_node(node_name: str, state: dict[str, Any]) -> TaskStatus:
    """按 LangGraph 节点推断 checkpoint 状态。"""

    if node_name in {"intent_router", "intent_parser", "constraint_builder", "constraint_clarifier"}:
        return TaskStatus.INTENT_PARSED
    if node_name in {
        "poi_collector",
        "poi_mix_recommend",
        "poi_activity_recommend",
        "poi_restaurant_recommend",
        "poi_lifestyle_recommend",
    }:
        return TaskStatus.CANDIDATES_RECALLED
    if node_name == "route_time_planner":
        return TaskStatus.PLAN_GENERATED
    if node_name in {"availability_checker", "verifier", "llm_critic", "ranker", "response_generator"}:
        return TaskStatus.PLAN_VALIDATED
    return checkpoint_status_from_state(state)


def build_agent_thinking_payload(
    node_name: str,
    patch: dict[str, Any],
    current_state: dict[str, Any],
) -> dict[str, Any]:
    """构造前端产品化进度文案，避免暴露内部英文日志和完整 state。"""

    latest_log = patch.get("logs", [])[-1] if patch.get("logs") else ""
    return {
        "agent": node_name,
        "title": agent_title(node_name),
        "message": product_message_for_node(node_name, latest_log, current_state),
        "summary": summarize_state_patch(patch),
    }


def agent_title(node_name: str) -> str:
    return {
        "intent_router": "理解需求",
        "intent_parser": "抽取意图",
        "constraint_builder": "整理条件",
        "constraint_clarifier": "判断是否追问",
        "planner_agent": "选择规划策略",
        "poi_collector": "检索地点",
        "poi_mix_recommend": "筛选活动/景点",
        "poi_activity_recommend": "筛选活动体验",
        "poi_restaurant_recommend": "筛选餐厅",
        "poi_lifestyle_recommend": "筛选生活方式",
        "route_time_planner": "生成路线时间线",
        "availability_checker": "检查可用性",
        "verifier": "校验方案",
        "llm_critic": "方案质检",
        "ranker": "综合排序",
        "response_generator": "生成回复",
    }.get(node_name, node_name)


def product_message_for_node(node_name: str, latest_log: str, state: dict[str, Any]) -> str:
    if node_name == "intent_router":
        return f"判断为 {state.get('intent_type') or '待确认'}，决定是否进入规划。"
    if node_name == "poi_collector":
        counts = {
            key: len(value) if isinstance(value, list) else 0
            for key, value in (state.get("candidate_pois", {}) or {}).items()
        }
        return f"已从数据库筛出 {sum(counts.values())} 个候选地点。"
    if node_name == "route_time_planner":
        return f"已生成 {len(state.get('candidate_plans', []) or [])} 个路线候选。"
    if node_name == "ranker":
        return f"已排序 {len(state.get('ranked_plans', []) or [])} 个方案。"
    if node_name == "response_generator":
        return "正在把结构化方案转成用户可读文本。"
    return latest_log or f"{agent_title(node_name)}已完成。"


def build_revision_state(
    previous_state: dict[str, Any],
    user_query: str,
    max_replanning_count: int,
    trace_id: str,
    run_id: str,
    revision_id: str,
) -> dict[str, Any]:
    """从上一轮完整 PlanState 克隆出可续跑状态。"""

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


def apply_revision_constraints(state: dict[str, Any], user_query: str) -> None:
    """把自然语言修正转成结构化约束，优先 LLM，规则只做兜底。"""

    constraints = state.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}
    parsed = extract_revision_constraints(
        user_query,
        previous_constraints=constraints,
        user_profile=state.get("user_profile", {}),
    )
    if parsed:
        apply_llm_revision_patch(constraints, parsed)
        state["constraints"] = constraints
        state["logs"] = [
            *state.get("logs", []),
            "已用 LLM 修正解析更新约束。",
        ]
        return
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
    excluded_keywords.extend(forbidden_terms(user_query))
    if "不要ktv" in text or "不要唱歌" in user_query:
        excluded_keywords.extend(["KTV", "唱歌"])
    constraints["avoid_tags"] = sorted({str(item) for item in avoid_tags if item})
    constraints["excluded_keywords"] = sorted({str(item) for item in excluded_keywords if item})
    state["constraints"] = constraints
    state["logs"] = [*state.get("logs", []), "已用规则兜底解析修正约束。"]


def apply_llm_revision_patch(constraints: dict[str, Any], parsed: dict[str, Any]) -> None:
    avoid_tags = list(constraints.get("avoid_tags", []) or [])
    excluded_keywords = list(constraints.get("excluded_keywords", []) or [])
    if parsed.get("indoor_preferred") is True:
        constraints["indoor_preferred"] = True
    avoid_tags.extend(str(item) for item in parsed.get("avoid_tags", []) or [] if str(item).strip())
    excluded_keywords.extend(str(item) for item in parsed.get("excluded_keywords", []) or [] if str(item).strip())
    for key in ("budget_strategy", "price_preference", "movement_policy"):
        value = parsed.get(key)
        if value:
            constraints[key] = str(value)
    try:
        if parsed.get("max_route_minutes") not in (None, ""):
            constraints["max_route_minutes"] = int(float(parsed["max_route_minutes"]))
            constraints["route_limit_is_hard"] = True
    except (TypeError, ValueError):
        pass
    activity_intents = parsed.get("activity_intents")
    if isinstance(activity_intents, list) and activity_intents:
        constraints["activity_intents"] = [item for item in activity_intents if isinstance(item, dict)][:8]
    preferred_categories = parsed.get("preferred_categories")
    if isinstance(preferred_categories, list) and preferred_categories:
        constraints["preferred_categories"] = [str(item) for item in preferred_categories if str(item).strip()][:8]
    constraints["avoid_tags"] = sorted({str(item) for item in avoid_tags if item})
    constraints["excluded_keywords"] = sorted({str(item) for item in excluded_keywords if item})


def forbidden_terms(text: str) -> list[str]:
    terms: list[str] = []
    for marker in ("不要", "别去", "不想去", "别安排"):
        if marker not in text:
            continue
        tail = text.split(marker, 1)[1]
        for separator in ("，", "。", ",", "；", ";"):
            tail = tail.split(separator, 1)[0]
        if tail.strip():
            terms.append(tail.strip())
    return terms[:5]


def run_revision_pipeline(state: dict[str, Any], recorder: TraceRecorder) -> dict[str, Any]:
    """跳过完整意图澄清，从 Planner 到 Response 重新生成方案。"""

    def run_node(node_name: str, node_fn) -> None:
        nonlocal state
        patch = recorder.time_node(
            node_name,
            lambda: node_fn(state),
            input_summary=summarize_state_patch(state),
        )
        state = merge_state_patch(state, patch)
        record_trace_event(
            "product_progress",
            {
                "event": "node_update",
                "node": node_name,
                "message": product_message_for_node(node_name, "", state),
            },
        )

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
    if verifier_route(state) == "rank":
        run_node("llm_critic", llm_critic_node)
    run_node("ranker", ranker_node)
    run_node("response_generator", response_generator_node)
    return state

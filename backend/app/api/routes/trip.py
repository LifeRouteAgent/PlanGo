from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import settings
from app.dag.langgraph_dag_config import life_route_graph
from app.models.schemas import AdjustPlanRequest, DataSourceStatusResponse, ExecutePlanRequest, TripPlanRequest, TripPlanResponse
from app.services.poi_repository import PoiRepository
from app.services.tool_harness import ToolHarness
from app.state.plan_state import create_initial_state


router = APIRouter(prefix="/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlanResponse)
def plan_trip(request: TripPlanRequest) -> TripPlanResponse:
    """同步规划接口。

    这个接口保留给测试和非流式调用方使用；前端主流程优先调用 `/trip/plan/stream`。
    """

    initial_state = create_initial_state(
        request.user_query,
        user_profile=request.user_profile,
        max_replanning_count=request.max_replanning_count,
    )
    result = life_route_graph.invoke(initial_state)
    return _build_trip_response(result)


@router.post("/plan/stream")
def stream_plan_trip(request: TripPlanRequest) -> StreamingResponse:
    """SSE 流式规划接口。

    使用 LangGraph `stream(..., stream_mode="updates")` 按节点输出，而不是先完整
    `invoke()` 再切文本。这样前端能在 Intent、Collector、Skill、Ranker 等节点完成时
    立即收到状态；当 Response Generator 产出文本后，再逐段推送 `response_chunk`。
    """

    def event_stream() -> Iterator[str]:
        event_queue: queue.Queue[tuple[str, dict[str, Any]] | None] = queue.Queue()
        current_state = create_initial_state(
            request.user_query,
            user_profile=request.user_profile,
            max_replanning_count=request.max_replanning_count,
        )

        def run_graph() -> None:
            nonlocal current_state
            try:
                for update in life_route_graph.stream(current_state, stream_mode="updates"):
                    for node_name, patch in update.items():
                        current_state = _merge_stream_patch(current_state, patch)
                        latest_log = patch.get("logs", [])[-1] if patch.get("logs") else ""
                        event_queue.put(
                            (
                                "agent_thinking",
                                _build_agent_thinking_payload(node_name, patch, current_state),
                            )
                        )
                        event_queue.put(
                            (
                                "agent_complete",
                                {
                                    "agent": node_name,
                                    "message": latest_log or f"{node_name} completed",
                                    "summary": _summarize_patch(patch),
                                },
                            )
                        )
                        event_queue.put(
                            (
                                "node_update",
                                {
                                    "node": node_name,
                                    "message": latest_log or f"{node_name} completed",
                                },
                            )
                        )
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
            },
        )

        if not response_text_sent:
            for chunk in _chunk_text(response.response_text):
                yield _sse_event("response_chunk", {"delta": chunk})
                time.sleep(0.03)

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


@router.post("/execute/stream")
def stream_execute_plan(request: ExecutePlanRequest) -> StreamingResponse:
    """Mock 执行方案流式接口。

    不调用真实预约、购票、打车 API，只根据方案内容生成可观察的执行步骤，并通过 SSE
    逐步返回 `running -> done` 状态。前端可以像真实执行一样逐个展示进度。
    """

    def event_stream() -> Iterator[str]:
        harness = ToolHarness(
            name="execution.mock.build_steps",
            timeout_seconds=3,
            max_retries=1,
            fallback=lambda: [
                {
                    "id": "execution_fallback",
                    "type": "plan_ready",
                    "title": "确认方案可执行",
                    "description": "执行步骤生成失败，已降级为方案确认。",
                }
            ],
        )
        harness_result = harness.run(_build_mock_execution_steps, request.plan)
        steps = harness_result.data if harness_result.success else []
        yield _sse_event(
            "execution_start",
            {
                "plan_id": request.plan.get("id"),
                "total_steps": len(steps),
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
        yield text[index:index + chunk_size]


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
        "route_time_planner": "路线时间规划",
        "availability_checker": "可用性检查",
        "verifier": "方案校验",
        "ranker": "方案排序",
        "response_generator": "响应生成",
    }
    return titles.get(node_name, node_name)


def _agent_message(node_name: str, patch: dict[str, Any], current_state: dict[str, Any]) -> str:
    """生成 Thinking 面板的一句话解释。"""

    if node_name == "intent_router":
        return f"判断为 {patch.get('intent_type', current_state.get('intent_type', '未知'))}，决定是否进入规划。"
    if node_name == "poi_collector":
        counts = {
            key: len(value)
            for key, value in patch.get("candidate_pois", {}).items()
            if isinstance(value, list)
        }
        return f"从本地数据源召回候选 POI：{counts or '等待结果'}。"
    if "recommend" in node_name:
        counts = {
            key: len(value)
            for key, value in patch.get("recommended_pois", {}).items()
            if isinstance(value, list)
        }
        return f"按偏好、预算、场景和风险给候选打分：{counts or '已完成'}。"
    if node_name == "route_time_planner":
        return f"生成 {len(patch.get('candidate_plans', []))} 个带时间线的候选方案。"
    if node_name == "verifier":
        errors = patch.get("errors", [])
        return "校验通过，进入排序。" if not errors else f"发现 {len(errors)} 个问题，准备回退或降级。"
    if node_name == "ranker":
        return f"综合偏好、距离、时间、预算排序出 {len(patch.get('ranked_plans', []))} 个方案。"
    if node_name == "response_generator":
        return "把结构化方案转成用户可读文本，并补充方案操作。"
    latest_log = patch.get("logs", [""])[-1] if patch.get("logs") else ""
    return latest_log or f"{node_name} 已完成。"


def _summarize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """把节点输出压缩成小摘要，供前端展示和排障。"""

    return {
        "candidate_categories": list(patch.get("candidate_pois", {}).keys())
        if isinstance(patch.get("candidate_pois"), dict)
        else [],
        "recommended_categories": list(patch.get("recommended_pois", {}).keys())
        if isinstance(patch.get("recommended_pois"), dict)
        else [],
        "candidate_plan_count": len(patch.get("candidate_plans", []))
        if isinstance(patch.get("candidate_plans"), list)
        else 0,
        "ranked_plan_count": len(patch.get("ranked_plans", []))
        if isinstance(patch.get("ranked_plans"), list)
        else 0,
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
    segments = plan.get("route_segments", []) if isinstance(plan.get("route_segments"), list) else []

    for item in items:
        category = str(item.get("category", ""))
        if category == "poi_restaurant":
            steps.append(
                {
                    "id": f"reserve_{item.get('id')}",
                    "type": "restaurant_reservation",
                    "title": f"预约餐厅：{item.get('name')}",
                    "description": "模拟提交人数、时间和备注，等待商家确认。",
                    "poi_id": item.get("id"),
                    "poi_name": item.get("name"),
                }
            )
        if category in {"poi_activity", "poi_attraction", "poi_entertainment"}:
            steps.append(
                {
                    "id": f"ticket_{item.get('id')}",
                    "type": "ticket_purchase",
                    "title": f"锁定门票/场次：{item.get('name')}",
                    "description": "模拟查询余票、选择场次并生成待支付订单。",
                    "poi_id": item.get("id"),
                    "poi_name": item.get("name"),
                }
            )

    for index, segment in enumerate(segments, start=1):
        steps.append(
            {
                "id": f"ride_{index}",
                "type": "ride_hailing",
                "title": f"叫车：{segment.get('from')} → {segment.get('to')}",
                "description": f"模拟预估 {segment.get('duration_minutes', 0)} 分钟，约 {segment.get('distance_km', 0)} km。",
                "from": segment.get("from"),
                "to": segment.get("to"),
                "transport_mode": segment.get("transport_mode"),
            }
        )

    if not steps:
        steps.append(
            {
                "id": "share_only",
                "type": "plan_ready",
                "title": "确认方案可执行",
                "description": "当前方案没有需要 mock 的预约、购票或打车步骤。",
            }
        )
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
    candidates = PoiRepository(limit_per_category=50).fetch_by_categories([category]).get(category, [])
    candidate_dicts = [
        dict(candidate)
        for candidate in candidates
        if str(candidate.get("id")) != str(poi_id)
    ]
    if not candidate_dicts:
        return _fallback_adjust_response(plan, poi_id, prompt, "当前类别没有可替换候选。")

    replacement = _pick_replacement(candidate_dicts, prompt, old_item)
    adjusted_plan = _apply_replacement(plan, old_item, replacement, prompt)
    return {
        "success": True,
        "plan": adjusted_plan,
        "old_poi": old_item,
        "new_poi": replacement,
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
        if "室内" in prompt and any(word in joined for word in ["室内", "商场", "影院", "ktv", "KTV", "棋牌", "桌游"]):
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
        "option_prompts": replacement.get("option_prompts")
        or ["再近一点", "换成室内", "换个更省钱的"],
    }
    adjusted["items"] = [
        replacement_item if str(item.get("id")) == old_id else item
        for item in adjusted.get("items", [])
    ]

    timeline = []
    for entry in adjusted.get("timeline", []) if isinstance(adjusted.get("timeline"), list) else []:
        if str(entry.get("poi_id")) == old_id:
            timeline.append(
                {
                    **entry,
                    "poi_id": replacement_item.get("id"),
                    "title": replacement_item.get("name"),
                    "address": replacement_item.get("address"),
                }
            )
        else:
            timeline.append(entry)
    adjusted["timeline"] = timeline
    adjusted["title"] = f"{adjusted.get('title', '方案')}（已局部调整）"
    adjusted["recommendation_reason"] = f"已按“{prompt}”替换单站，其他安排保持不变。"
    return adjusted


def _rough_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    """粗略距离，用于局部替换排序；真实路线仍由 Route Planner/高德阶段负责。"""

    try:
        return abs(float(a.get("lat", 0)) - float(b.get("lat", 0))) * 111 + abs(
            float(a.get("lon", 0)) - float(b.get("lon", 0))
        ) * 85
    except (TypeError, ValueError):
        return 99


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

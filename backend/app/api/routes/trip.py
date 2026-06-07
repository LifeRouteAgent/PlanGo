from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from app.config import settings

# 导入 trip 相关接口的请求体和响应体模型
from app.api.schemas.trip import (
    AdjustPlanRequest,          # 调整方案请求体
    DataSourceStatusResponse,   # 数据源状态响应体
    ExecutePlanRequest,         # 执行方案请求体
    RevisePlanRequest,          # 修改方案请求体
    TripPlanRequest,            # 生成行程方案请求体
    TripPlanResponse,           # 生成行程方案响应体
)
from app.integrations.calendar_service import build_plan_ics
from app.runtime.checkpoint_store import CheckpointStore, TaskStatus, make_idempotency_key

# 导入 Memory 事件队列，用于异步写入用户反馈、行为记录等
from app.memory.memory_event_queue import MemoryEventQueue

# 导入 Memory 服务，用于清空记忆、搜索记忆、获取用户画像等
from app.memory.memory_service import MemoryService

# 导入 POI 仓库，用于查询数据库中的地点数据
from app.repositories.poi_repository import PoiRepository

# 导入 Trace 相关工具，用于记录运行链路、生成 trace_id、设置上下文
from app.observability.trace_recorder import TraceRecorder, new_id, record_trace_event, set_trace_context

# 导入 trip 相关业务服务
from app.planning.trip_services import (
    TaskRecoveryService,     # 任务恢复服务，用于断点续跑、恢复决策
    TripExecutionService,    # 行程执行服务，用于模拟执行、风险判断
    TripPlanningService,     # 行程规划服务，用于生成完整行程方案
    TripRevisionService,     # 行程修改服务，用于根据用户反馈调整方案
    TripStreamingService,    # 行程流式规划服务，用于 SSE 输出规划过程
)

# 导入观测相关工具函数
from app.observability.trip_progress import (
    build_agent_thinking_payload as _build_agent_thinking_payload,  # 构造 Agent 思考过程展示数据
    effective_query_for_request as _effective_query_for_request,    # 提取实际用于规划的用户 query
    trace_events_for_node as _trace_events_for_node,                # 获取某个节点的 trace 事件
)

# 创建 trip 路由对象
# prefix="/trip" 表示这个文件里的接口都会以 /trip 开头
# tags=["trip"] 表示接口文档中归类到 trip 分组
router = APIRouter(prefix="/trip", tags=["trip"])


# 定义 GET /trip/client-config 接口
# 前端调用这个接口获取客户端需要的配置，例如高德地图 key
@router.get("/client-config")
def get_client_config() -> dict[str, str]:
    # 返回高德地图前端 key，以及安全密钥字段
    return {"amap_key": settings.amap_api_key, "amap_security_js_code": ""}


# 定义 POST /trip/plan 接口
# 用于普通非流式生成行程规划
@router.post("/plan", response_model=TripPlanResponse)
def plan_trip(request: TripPlanRequest) -> TripPlanResponse:
    # 创建 TripPlanningService，并调用 plan 方法生成行程方案
    return TripPlanningService().plan(request)


# 定义 POST /trip/plan/stream 接口
# 用于流式生成行程规划
@router.post("/plan/stream")
def stream_plan_trip(request: TripPlanRequest) -> StreamingResponse:
    # 调用 TripStreamingService().stream(request) 得到事件生成器
    # 再包装成 SSE 流式响应
    return _streaming_response(TripStreamingService().stream(request))


# 定义 POST /trip/plan/revise/stream 接口
# 用于流式修改已有行程方案
@router.post("/plan/revise/stream")
def stream_revise_plan(request: RevisePlanRequest) -> StreamingResponse:
    # 调用 TripRevisionService().stream(request) 得到修改过程事件流
    # 再包装成 SSE 流式响应
    return _streaming_response(TripRevisionService().stream(request))


# 定义 POST /trip/execute/stream 接口
# 用于流式执行行程方案
@router.post("/execute/stream")
def stream_execute_plan(request: ExecutePlanRequest) -> StreamingResponse:
    """只模拟执行，不调用真实预约、购票、打车或支付接口。"""

    # 定义内部生成器函数，用来持续向前端推送 SSE 事件
    def events() -> Iterator[str]:
        # 获取 session_id；如果请求中没有，则使用默认 execution_session
        session_id = request.session_id or "execution_session"

        # 获取 trace_id；如果请求中没有，则生成一个新的 trace_id
        trace_id = request.trace_id or new_id("trace")

        # 获取 run_id；如果请求中没有，则生成一个新的 run_id
        run_id = request.run_id or new_id("run")

        # 设置当前执行链路上下文，方便后续日志、trace、checkpoint 记录
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)

        # 创建任务断点存储对象
        checkpoint = CheckpointStore()

        # 获取 task_id
        # 优先使用请求里的 task_id
        # 其次使用 plan 里的 task_id
        # 如果都没有，则生成一个新的 task_id
        task_id = request.task_id or str(request.plan.get("task_id") or new_id("task"))

        # 如果当前 task_id 没有已有 checkpoint，则创建一个新的任务记录
        if not checkpoint.load(task_id):
            # 创建 checkpoint 任务记录
            checkpoint.create(session_id=session_id, user_id=session_id, trace_id=trace_id, task_id=task_id)

        # 根据 plan 生成需要执行的步骤列表
        steps = _execution_steps(request.plan)

        # 推送执行开始事件
        yield _sse("execution_start", {
            "plan_id": request.plan.get("id"),  # 当前方案 ID
            "total_steps": len(steps),          # 总执行步骤数
            "task_id": task_id,                 # 当前执行任务 ID
        })

        # 创建行程执行服务
        service = TripExecutionService()

        # 获取已经验证过的方案 item id
        # 用于后续判断某些动作是否针对已确认目标
        valid_ids = service.validated_item_ids(request.plan)

        # 遍历每一个执行步骤
        for step in steps:
            # 获取当前步骤的风险等级
            risk = service.risk_level_for_step(step)

            # 获取当前步骤对应的目标 ID
            # 优先使用 poi_id，其次使用 step id，最后使用 plan id
            target_id = str(step.get("poi_id") or step.get("id") or request.plan.get("id") or "")

            # 生成幂等 key
            # 作用：避免同一个动作重复执行，例如重复导出、重复预约、重复下单
            key = make_idempotency_key(
                user_id=session_id,                         # 用户 ID，这里临时用 session_id
                task_id=task_id,                             # 当前任务 ID
                action_type=str(step.get("type") or "step"), # 动作类型
                target_id=target_id,                         # 动作目标 ID
            )

            # 记录当前步骤开始执行
            checkpoint.append_action(task_id, {
                "action_id": str(step["id"]),                 # 动作 ID
                "type": str(step["type"]),                    # 动作类型
                "risk_level": int(risk),                      # 风险等级
                "status": "running",                         # 当前状态：执行中
                "idempotency_key": key,                       # 幂等 key
                "request": {**step, "validated_item_ids": valid_ids},  # 执行请求参数
                "result": None,                               # 当前还没有执行结果
            })

            # 向前端推送当前步骤开始执行事件
            yield _sse("execution_step", {**step, "status": "running"})

            # 暂停 0.15 秒，用于模拟真实执行耗时
            time.sleep(0.15)

            # 记录当前步骤执行成功
            checkpoint.append_action(task_id, {
                "action_id": str(step["id"]),  # 动作 ID
                "type": str(step["type"]),     # 动作类型
                "risk_level": int(risk),       # 风险等级
                "status": "success",          # 当前状态：成功
                "idempotency_key": key,        # 幂等 key
                "request": step,               # 原始请求参数
                "result": {"simulated": True}, # 执行结果：模拟执行
            })

            # 向前端推送当前步骤完成事件
            yield _sse("execution_step", {
                **step,                    # 原步骤信息
                "status": "done",         # 状态：完成
                "result": "模拟执行完成",   # 前端展示文本
            })

        # 执行完成后，把用户执行方案的行为写入 Memory 事件队列
        MemoryEventQueue().publish_plan_feedback(
            request.plan,                         # 当前执行的方案
            user_id=session_id,                   # 用户 ID
            stage="plan_executed",                # 行为阶段：方案已执行
            feedback={"source": "execute_stream"},# 反馈来源
            trace_id=trace_id,                    # trace ID
            run_id=run_id,                        # run ID
            session_id=session_id,                # session ID
        )

        # 推送执行完成事件
        yield _sse("execution_done", {
            "status": "done",                         # 总状态：完成
            "message": "模拟执行完成，未调用真实第三方 API。", # 提示前端这只是模拟执行
        })

    # 把内部生成器包装成 StreamingResponse 返回给前端
    return _streaming_response(events())


# 定义 POST /trip/plan/adjust 接口
# 用于兼容旧前端的单个 POI 替换功能
@router.post("/plan/adjust")
def adjust_plan(request: AdjustPlanRequest) -> dict[str, Any]:
    """兼容旧前端的单站替换；多轮调整应使用 V2 plan_adjustment。"""

    # 复制一份 plan，避免直接修改原始请求对象
    plan = dict(request.plan)

    # 从 plan 中取出 items
    # 只保留 dict 类型的 item，避免脏数据
    items = [dict(item) for item in plan.get("items", []) if isinstance(item, dict)]

    # 查找用户想替换的 POI 在 items 中的索引
    index = next((i for i, item in enumerate(items) if str(item.get("id")) == request.poi_id), None)

    # 如果没找到对应 POI，返回失败
    if index is None:
        return {"ok": False, "plan": plan, "message": "没有找到要替换的地点。"}

    # 取出旧 POI
    old = items[index]

    # 根据旧 POI 的 category，从数据库中查询同类别候选
    alternatives = PoiRepository(limit_per_category=10).fetch_by_categories([str(old.get("category") or "")])

    # 从候选中找一个不同于当前 POI 的替代地点
    replacement = next(
        (
            dict(item)
            for item in alternatives.get(str(old.get("category") or ""), [])
            if str(item.get("id")) != request.poi_id
        ),
        None,
    )

    # 如果没有找到替代地点，返回失败
    if replacement is None:
        return {"ok": False, "plan": plan, "message": "当前类别没有可替换候选。"}

    # 用替代地点替换原来的 item
    items[index] = replacement

    # 更新方案内容
    plan.update({
        "items": items,  # 更新后的地点列表
        "title": f"{plan.get('title', '方案')}（已局部调整）",  # 给标题加上已调整标记
        "recommendation_reason": f"已按“{request.prompt}”替换单站，建议重新确认路线和预算。",  # 更新推荐理由
    })

    # 返回调整成功结果
    return {
        "ok": True,                       # 表示调整成功
        "plan": plan,                     # 返回新方案
        "message": "已完成单站替换。",      # 前端提示语
        "issues": plan.get("issues", []), # 保留原方案中的问题列表
    }


# 定义 POST /trip/calendar/ics 接口
# 用于把方案导出成日历 ICS 文件
@router.post("/calendar/ics")
def export_calendar_ics(request: ExecutePlanRequest) -> Response:
    # 根据方案生成 ICS 格式文本
    ics_text = build_plan_ics(request.plan)

    # 如果请求中有 session_id，则记录用户导出日历的行为
    if request.session_id:
        # 把导出日历行为写入 Memory 事件队列
        MemoryEventQueue().publish_plan_feedback(
            request.plan,                         # 当前方案
            user_id=request.session_id,           # 用户 ID
            stage="plan_exported_calendar",       # 行为阶段：导出日历
            feedback={"source": "calendar_ics"},  # 反馈来源
            trace_id=request.trace_id or "",      # trace ID
            run_id=request.run_id or "",          # run ID
            session_id=request.session_id,         # session ID
        )

    # 返回 ICS 文件响应
    return Response(
        content=ics_text,                         # 文件内容
        media_type="text/calendar; charset=utf-8",# 响应类型：日历文件
        headers={
            "Content-Disposition": 'attachment; filename="liferoute-plan.ics"'  # 告诉浏览器下载文件
        },
    )


# 定义 GET /trip/trace/{trace_id} 接口
# 用于读取某次规划 / 执行的 trace 记录
@router.get("/trace/{trace_id}")
def get_trace(trace_id: str) -> dict[str, Any]:
    # 从 TraceRecorder 中读取 trace 数据
    return TraceRecorder.read(trace_id)


# 定义 GET /trip/task/{task_id} 接口
# 用于读取某个任务的 checkpoint 状态
@router.get("/task/{task_id}")
def get_task_checkpoint(task_id: str) -> dict[str, Any]:
    # 返回指定任务的状态、动作历史、恢复信息等
    return TaskRecoveryService().task_payload(task_id)


# 定义 POST /trip/task/{task_id}/resume 接口
# 用于请求恢复某个中断任务
@router.post("/task/{task_id}/resume")
def resume_task_checkpoint(task_id: str) -> dict[str, Any]:
    # 返回任务恢复决策
    return TaskRecoveryService().resume_decision(task_id)


# 定义 GET /trip/task/{task_id}/resume-decision 接口
# 用于查询某个任务是否可以恢复、应该如何恢复
@router.get("/task/{task_id}/resume-decision")
def get_task_resume_decision(task_id: str) -> dict[str, Any]:
    # 返回任务恢复决策
    return TaskRecoveryService().resume_decision(task_id)


# 定义 GET /trip/evals/runtime-summary 接口
# 用于获取运行时评测摘要
@router.get("/evals/runtime-summary")
def get_runtime_eval_summary() -> dict[str, Any]:
    # 返回 runtime 层面的评测统计
    return TaskRecoveryService().runtime_summary()


# 定义 GET /trip/observability/node-metrics 接口
# 用于获取规划图节点级别的运行指标
@router.get("/observability/node-metrics")
def get_node_metrics(trace_id: str | None = Query(default=None)) -> dict[str, Any]:
    # 如果传入 trace_id，则查询指定 trace 的节点指标
    # 如果不传，则查询整体节点指标
    return TaskRecoveryService().node_metrics(trace_id)


# 定义 GET /trip/observability/runtime-health 接口
# 用于获取运行时健康状态
@router.get("/observability/runtime-health")
def get_runtime_health() -> dict[str, Any]:
    # 返回 runtime 健康状态，例如错误率、恢复情况、节点状态等
    return TaskRecoveryService().runtime_health()


# 定义 DELETE /trip/memory 接口
# 用于清空某个用户的 Memory
@router.delete("/memory")
def clear_memory(user_id: str | None = Query(default=None)) -> dict[str, Any]:
    # 如果传入 user_id，则清空该用户的记忆
    # 如果没传，则默认清空 default 用户的记忆
    MemoryService().clear(user_id=user_id or "default")

    # 返回清空成功
    return {"ok": True}


# 定义 GET /trip/memory/search 接口
# 用于语义搜索用户 Memory
@router.get("/memory/search")
def search_memory(
    query: str = Query(default=""),                 # 搜索关键词，默认空字符串
    limit: int = Query(default=5, ge=1, le=20),      # 返回数量，最小 1，最大 20
    user_id: str = Query(default="default"),         # 用户 ID，默认 default
) -> dict[str, Any]:
    # 调用 MemoryService 进行语义搜索，并返回搜索结果
    return {"items": MemoryService().semantic_search(query, limit=limit, user_id=user_id)}


# 定义 GET /trip/memory/profile 接口
# 用于获取用户画像 Memory
@router.get("/memory/profile")
def get_memory_profile(user_id: str = Query(default="default")) -> dict[str, Any]:
    # 返回指定用户的画像数据
    return MemoryService().profile_payload(user_id=user_id)


# 定义 POST /trip/memory/rebuild-index 接口
# 用于重建某个用户的 Memory 向量索引
@router.post("/memory/rebuild-index")
def rebuild_memory_index(user_id: str = Query(default="default")) -> dict[str, Any]:
    # 调用 MemoryService 重建向量索引
    return MemoryService().rebuild_vector_index(user_id=user_id)


# 定义 GET /trip/memory/clusters 接口
# 用于查看 Memory 聚类结果
@router.get("/memory/clusters")
def get_memory_clusters() -> dict[str, Any]:
    # 返回用户记忆聚类结果
    return {"clusters": MemoryService().clusters()}


# 定义 GET /trip/data-source 接口
# 用于查看当前 POI 数据源状态
@router.get("/data-source", response_model=DataSourceStatusResponse)
def data_source_status() -> DataSourceStatusResponse:
    # 尝试读取数据库表数量
    try:
        # 查询每张 POI 表的数据量
        counts = PoiRepository().table_counts()

        # 返回数据源可用状态
        return DataSourceStatusResponse(
            enabled=settings.use_database,                     # 是否启用数据库
            source="mysql" if settings.use_database else "mock",# 数据来源：mysql 或 mock
            database_name=settings.database_name,               # 数据库名称
            table_counts=counts,                                # 各表数据量
        )

    # 如果数据库不可用或查询失败，进入异常分支
    except Exception as exc:  # noqa: BLE001
        # 返回数据源不可用状态
        return DataSourceStatusResponse(
            enabled=False,                      # 数据源不可用
            source="unavailable",              # 来源标记为不可用
            database_name=settings.database_name,# 数据库名称
            error=str(exc),                     # 错误信息
        )


# 封装 SSE 流式响应
def _streaming_response(events: Iterator[str]) -> StreamingResponse:
    # 返回 FastAPI StreamingResponse
    return StreamingResponse(
        events,                                      # 事件生成器
        media_type="text/event-stream",              # SSE 必须使用 text/event-stream
        headers={
            "Cache-Control": "no-cache",             # 禁止缓存，保证实时输出
            "X-Accel-Buffering": "no",               # 禁用 Nginx 缓冲，避免流式输出被攒起来
        },
    )


# 封装单条 SSE 消息
def _sse(event: str, data: dict[str, Any]) -> str:
    # SSE 格式：
    # event: 事件名称
    # data: JSON 数据
    # 空行表示一条事件结束
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# 根据 plan 生成模拟执行步骤
def _execution_steps(plan: dict[str, Any]) -> list[dict[str, Any]]:
    # 遍历 plan["items"]，为每个 POI 生成一个 visit 步骤
    steps = [
        {
            "id": f"visit_{index}",             # 步骤 ID，例如 visit_1
            "type": "visit",                   # 步骤类型：访问地点
            "poi_id": item.get("id"),          # 当前 POI 的 ID
            "title": f"确认前往 {item.get('name')}", # 前端展示标题
        }
        # enumerate 从 1 开始，让 visit 编号更符合用户习惯
        for index, item in enumerate(plan.get("items", []), start=1)

        # 只处理 dict 类型的 item，避免异常数据
        if isinstance(item, dict)
    ]

    # 最后追加一个生成日历提醒的步骤
    steps.append({
        "id": "calendar_export",       # 步骤 ID
        "type": "calendar_export",     # 步骤类型：日历导出
        "title": "生成日历提醒",        # 前端展示标题
    })

    # 返回完整执行步骤列表
    return steps
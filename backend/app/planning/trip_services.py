from __future__ import annotations  # 启用延迟类型注解，避免类型在运行时立即求值，适合解决循环引用和提升兼容性

import json  # 用于 JSON 序列化，比如 SSE 输出时把 dict 转成 JSON 字符串
import threading  # 用于启动后台线程，比如异步执行规划任务
from collections.abc import Iterator  # 引入迭代器类型，用于标注 stream 返回值
from typing import Any  # Any 表示任意类型，用于不确定结构的 dict、对象等

from app.bus.event import Event  # 导入事件对象，用于封装运行过程中的事件
from app.bus.event_bus import publish_event_sync  # 导入同步发布事件的方法
from app.bus.subscribers.frontend_subscriber import install_frontend_progress_subscriber  # 安装前端进度订阅器
from app.planning.graph_builder import planning_graph_v2  # 导入 V2 版本的规划图，也就是核心 LangGraph 工作流
from app.planning.state import PlanningState, create_planning_state, planning_state_to_legacy  # 导入规划状态模型、状态创建函数、状态转旧格式函数
from app.api.schemas.trip import RevisePlanRequest, TripPlanRequest, TripPlanResponse  # 导入 API 请求和响应的数据模型
from app.runtime.checkpoint_store import CheckpointStore, TaskStatus  # 导入任务检查点存储和任务状态枚举
from app.integrations.amap_weather_service import AmapWeatherService  # 导入高德天气服务，用于给方案补充天气信息
from app.memory.memory_service import MemoryService  # 导入记忆服务，用于管理用户长期偏好或历史信息
from app.planning.policy_config import policy_config  # 导入策略配置，比如执行动作风险等级
from app.runtime.runtime_store import get_runtime_store  # 获取运行时存储，用于查看任务、节点指标等
from app.context.session_store import SessionStore  # 导入会话存储，用于管理 session_id 和历史轮次
from app.observability.trace_recorder import new_id, set_trace_context  # 导入链路追踪 ID 生成和上下文设置方法
from app.observability.trip_progress import build_agent_thinking_payload  # 构造前端展示用的 agent 思考过程 payload
from app.streaming.stream_manager import stream_manager  # 导入流式管理器，用于主动推送规划进度

install_frontend_progress_subscriber()  # 启动前端进度订阅器，让 bus 事件可以被前端监听到


class TripPlanningService:
    """Planning Graph V2 同步入口。"""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,  # 可选传入会话存储，方便测试或依赖注入
        memory: MemoryService | None = None,  # 可选传入记忆服务
        checkpoint: CheckpointStore | None = None,  # 可选传入检查点存储
    ) -> None:
        self.session_store = session_store or SessionStore()  # 如果外部没传 session_store，就创建默认 SessionStore
        self.memory = memory or MemoryService()  # 如果外部没传 memory，就创建默认 MemoryService
        self.checkpoint = checkpoint or CheckpointStore()  # 如果外部没传 checkpoint，就创建默认 CheckpointStore

    def plan(self, request: TripPlanRequest) -> TripPlanResponse:
        session_id = self.session_store.ensure_session_id(request.session_id)  # 确保本次请求有 session_id，没有则创建
        trace_id = request.trace_id or new_id("trace")  # 获取或生成 trace_id，用于链路追踪
        run_id = request.run_id or new_id("run")  # 获取或生成 run_id，用于标识本次运行
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)  # 设置当前请求的追踪上下文

        task = self.checkpoint.create(  # 在 checkpoint 中创建一个任务记录
            session_id=session_id,  # 保存当前会话 ID
            user_id=request.user_id or session_id,  # 如果没有 user_id，就用 session_id 兜底
            trace_id=trace_id,  # 保存 trace_id
        )

        result = run_v2_request_to_legacy(request, session_id=session_id)  # 执行 V2 规划流程，并转换成旧版兼容格式

        result.update(  # 给结果补充任务和追踪相关 ID
            {
                "task_id": str(task["task_id"]),  # 写入任务 ID
                "trace_id": trace_id,  # 写入 trace_id
                "run_id": run_id,  # 写入 run_id
                "session_id": session_id,  # 写入 session_id
            }
        session_id = self.session_store.ensure_session_id(request.session_id)
        trace_id = request.trace_id or new_id("trace")
        run_id = request.run_id or new_id("run")
        set_trace_context(trace_id=trace_id, run_id=run_id, session_id=session_id)
        task = self.checkpoint.create(
            session_id=session_id, user_id=request.user_id or session_id, trace_id=trace_id
        )
        result = run_v2_request_to_legacy(request, session_id=session_id)
        result.update({
            "task_id": str(task["task_id"]),
            "trace_id": trace_id,
            "run_id": run_id,
            "session_id": session_id,
        })
        self.checkpoint.save_from_plan_state(
            result,
            status=checkpoint_status_from_state(result),
            task_id=str(task["task_id"]),
        )

        self.checkpoint.save_from_plan_state(  # 将本次规划结果保存到 checkpoint
            result,  # 保存规划结果
            status=checkpoint_status_from_state(result),  # 根据规划状态推断任务状态
            task_id=str(task["task_id"]),  # 指定任务 ID
        )

        response = build_trip_response(result, include_debug=request.debug)  # 把内部 dict 结果组装成 TripPlanResponse

        self.session_store.save_turn(  # 保存本轮对话记录
            session_id=session_id,  # 当前会话 ID
            trace_id=trace_id,  # 当前 trace ID
            run_id=run_id,  # 当前 run ID
            user_query=request.user_query,  # 用户原始输入
            state=result,  # 当前规划状态
            response=response.model_dump(),  # 响应对象转 dict 后保存
        )

        return response  # 返回最终响应


class TripStreamingService:
    """Planning Graph V2 SSE 入口。"""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,  # 可选会话存储
        memory: MemoryService | None = None,  # 可选记忆服务
        checkpoint: CheckpointStore | None = None,  # 可选检查点存储
    ) -> None:
        self.session_store = session_store or SessionStore()  # 初始化会话存储
        self.memory = memory or MemoryService()  # 初始化记忆服务
        self.checkpoint = checkpoint or CheckpointStore()  # 初始化检查点存储

    def stream(self, request: TripPlanRequest) -> Iterator[str]:
        yield from stream_v2_request(request)  # 把 V2 流式规划结果逐条 yield 出去，供 SSE 返回给前端


class TripRevisionService:
    """修订请求统一进入 V2 plan_adjustment 分支。"""

    def __init__(
        self,
        *,
        session_store: SessionStore | None = None,  # 可选会话存储
        memory: MemoryService | None = None,  # 可选记忆服务
        checkpoint: CheckpointStore | None = None,  # 可选检查点存储
    ) -> None:
        self.session_store = session_store or SessionStore()  # 初始化会话存储
        self.memory = memory or MemoryService()  # 初始化记忆服务
        self.checkpoint = checkpoint or CheckpointStore()  # 初始化检查点存储

    def stream(self, request: RevisePlanRequest) -> Iterator[str]:
        yield from stream_v2_request(  # 修订请求也复用普通规划的流式入口
            TripPlanRequest(  # 把 RevisePlanRequest 转成 TripPlanRequest
                user_query=request.user_query,  # 修订时用户输入的新要求
                session_id=request.session_id,  # 复用原会话 ID
                max_replanning_count=request.max_replanning_count,  # 最大重规划次数
            )
        )


class TripExecutionService:
    def risk_level_for_step(self, step: dict[str, Any]) -> int:
        action_type = str(step.get("type") or step.get("action_type") or "")  # 从步骤中读取动作类型，兼容 type 和 action_type 两种字段
        return policy_config.risk_policy.risk_level_for(action_type, default=1)  # 根据动作类型查询风险等级，默认风险等级为 1

    def validated_item_ids(self, plan: dict[str, Any]) -> list[str]:
        return [  # 返回已经校验过的计划项 ID 列表
            str(item.get("id"))  # 将 item 的 id 转成字符串
            for item in plan.get("items", [])  # 遍历 plan 里的 items
            if isinstance(item, dict) and item.get("id")  # 只保留 dict 且存在 id 的 item
        ]


class TaskRecoveryService:
    def __init__(self, checkpoint: CheckpointStore | None = None) -> None:
        self.checkpoint = checkpoint or CheckpointStore()  # 初始化 checkpoint，用于任务恢复

    def task_payload(self, task_id: str) -> dict[str, Any]:
        task = self.checkpoint.load(task_id)  # 根据 task_id 加载任务
        return {"ok": bool(task), "task": task}  # 返回任务是否存在，以及任务内容

    def resume_decision(self, task_id: str) -> dict[str, Any]:
        return self.checkpoint.resume(task_id)  # 根据 checkpoint 判断该任务能否恢复、从哪里恢复

    def runtime_summary(self) -> dict[str, Any]:
        runtime = get_runtime_store()  # 获取运行时存储对象
        tasks = runtime.list_tasks()  # 获取运行时任务列表
        metrics = runtime.list_node_metrics()  # 获取所有节点执行指标

        return {
            "task_count": len(tasks),  # 当前运行时任务数量
            "trace_count": len({item.get("trace_id") for item in metrics if item.get("trace_id")}),  # 去重后的 trace 数量
            "node_metric_count": len(metrics),  # 节点指标记录数量
            "recoverable_task_count": len(self.checkpoint.recoverable_tasks()),  # 可恢复任务数量
        }

    def node_metrics(self, trace_id: str | None = None) -> dict[str, Any]:
        metrics = get_runtime_store().list_node_metrics(trace_id)  # 获取指定 trace_id 的节点指标；如果 trace_id 为空则获取全部
        return {"trace_id": trace_id or "", "count": len(metrics), "metrics": metrics}  # 返回 trace_id、数量和指标详情

    def runtime_health(self) -> dict[str, Any]:
        return get_runtime_store().health()  # 返回运行时健康状态


def run_v2_request_to_legacy(request: TripPlanRequest, *, session_id: str) -> dict[str, Any]:
    initial = create_v2_initial_state(request, session_id=session_id)  # 根据请求创建 V2 初始 PlanningState
    return run_v2_state_to_legacy(initial)  # 执行 V2 图，并转换成旧版兼容 dict


def create_v2_initial_state(request: TripPlanRequest, *, session_id: str) -> PlanningState:
    return create_planning_state(  # 调用统一工厂函数创建 PlanningState
        request.user_query,  # 用户输入的原始 query
        session_id=session_id,  # 当前会话 ID
        user_id=request.user_id or session_id,  # 用户 ID，没有则用 session_id 兜底
        city=str(request.user_profile.get("city") or "") or None,  # 从 user_profile 中取城市，空字符串转成 None
        message_id=request.message_id or "",  # 消息 ID，没有则为空字符串
        timezone=request.timezone,  # 请求时区
        source=request.source,  # 请求来源，比如 api、web 等
        geo_location=request.geo_location,  # 浏览器或客户端传入的地理位置
        manual_origin=request.manual_origin,  # 用户手动输入或 LLM 识别出的出发点
    )


def run_v2_state_to_legacy(initial: PlanningState) -> dict[str, Any]:
    _publish_run_event(initial, "run_started", status="running")  # 发布运行开始事件

    try:
        result = planning_graph_v2.invoke(initial)  # 同步执行 Planning Graph V2

        state = result if isinstance(result, PlanningState) else PlanningState.model_validate(result)  # 保证结果一定是 PlanningState 类型

        legacy = planning_state_to_legacy(state)  # 将 V2 PlanningState 转换成旧版兼容 dict

        _publish_run_event(  # 发布运行完成事件
            state,  # 当前最终状态
            "run_finished",  # 事件类型：运行完成
            status="success",  # 状态：成功
            payload={
                "plan_count": len(legacy.get("ranked_plans") or []),  # 输出方案数量
                "request_type": legacy.get("intent_type"),  # 请求意图类型
            },
        )

        return legacy  # 返回旧版兼容格式结果

    except Exception as exc:
        _publish_run_event(  # 如果运行异常，发布失败事件
            initial,  # 使用初始状态作为事件上下文
            "run_failed",  # 事件类型：运行失败
            status="failed",  # 状态：失败
            payload={"error_summary": exc.__class__.__name__},  # 只记录异常类名，避免泄漏过多错误细节
        )
        raise  # 继续抛出异常，交给上层处理


def start_v2_plan_progress(request: TripPlanRequest) -> dict[str, str]:
    session_id = SessionStore().ensure_session_id(request.session_id)  # 创建或获取 session_id

    initial = create_v2_initial_state(request, session_id=session_id)  # 创建 V2 初始状态

    request_id = initial.state_meta.request_id  # 从状态元信息中获取 request_id

    stream_manager.register(request_id)  # 在流式管理器中注册这个 request_id

    thread = threading.Thread(  # 创建一个后台线程执行规划任务
        target=_run_v2_progress_job,  # 线程执行函数
        args=(initial,),  # 传入初始状态作为参数
        name=f"planning-progress-{request_id}",  # 设置线程名称，方便排查问题
        daemon=True,  # 设置为守护线程，主进程退出时该线程自动退出
    )

    thread.start()  # 启动后台线程

    return {
        "request_id": request_id,  # 返回请求 ID，前端用它订阅流
        "run_id": initial.state_meta.state_id,  # 返回运行 ID
        "stream_url": f"/api/plans/{request_id}/stream",  # 返回前端可连接的 SSE 流地址
    }


def _run_v2_progress_job(initial: PlanningState) -> None:
    try:
        legacy = run_v2_state_to_legacy(initial)  # 执行 V2 规划，并转旧版兼容格式

        legacy["session_id"] = initial.state_meta.session_id  # 补充 session_id

        response = build_trip_response(legacy)  # 构造标准 TripPlanResponse

        import asyncio  # 在函数内部导入 asyncio，用于运行异步发送逻辑

        asyncio.run(  # 在当前线程中运行异步任务
            stream_manager.send(  # 向前端流发送最终结果
                initial.state_meta.request_id,  # 指定发送给哪个 request_id
                {
                    "type": "final_result",  # 消息类型：最终结果
                    "request_id": initial.state_meta.request_id,  # 当前请求 ID
                    "run_id": initial.state_meta.state_id,  # 当前运行 ID
                    "response": response.model_dump(mode="json"),  # 响应对象转 JSON 兼容 dict
                },
            )
        )

    finally:
        import asyncio  # 再次导入 asyncio，用于关闭流

        asyncio.run(stream_manager.close(initial.state_meta.request_id))  # 无论成功失败，最后都关闭当前 request_id 对应的流


def _publish_run_event(
    state: PlanningState,  # 当前规划状态
    event_type: str,  # 事件类型，比如 run_started、run_finished、run_failed
    *,
    status: str,  # 事件状态，比如 running、success、failed
    payload: dict[str, Any] | None = None,  # 事件附加数据
) -> None:
    publish_event_sync(  # 同步发布事件
        Event(  # 构造事件对象
            event_type=event_type,  # 设置事件类型
            request_id=state.state_meta.request_id,  # 设置请求 ID
            run_id=state.state_meta.state_id,  # 设置运行 ID
            conversation_id=state.state_meta.session_id or None,  # 设置会话 ID，没有则为 None
            user_id=state.state_meta.user_id or None,  # 设置用户 ID，没有则为 None
            status=status,  # 设置事件状态
            payload=payload or {},  # 设置事件数据，没有则为空 dict
        )
    )


def stream_v2_request(request: TripPlanRequest) -> Iterator[str]:
    session_id = SessionStore().ensure_session_id(request.session_id)  # 创建或获取 session_id

    initial = create_planning_state(  # 创建 V2 初始规划状态
        request.user_query,  # 用户输入
        session_id=session_id,  # 当前会话 ID
        user_id=request.user_id or session_id,  # 用户 ID，没有则使用 session_id
        city=str(request.user_profile.get("city") or "") or None,  # 从用户画像中获取城市
        message_id=request.message_id or "",  # 消息 ID，没有则为空字符串
        timezone=request.timezone,  # 时区
        source=request.source,  # 请求来源
        geo_location=request.geo_location,  # 浏览器定位
        manual_origin=request.manual_origin,  # 手动起点或识别出的起点
    )

    current = initial  # 当前状态初始化为 initial

    yield sse_event(  # 发送第一条 SSE 状态事件
        "status",  # SSE 事件名
        {
            "stage": "planning_v2",  # 当前阶段
            "session_id": session_id,  # 当前会话 ID
            "message": "Planning Graph V2 已启动。",  # 给前端展示的提示文案
        },
    )

    for update in planning_graph_v2.stream(initial, stream_mode="updates"):  # 以流式方式执行图，每个节点完成后返回更新
        for node_name, patch in update.items():  # 遍历本次更新中的节点名和该节点产生的状态增量
            payload = current.model_dump(mode="python")  # 把当前 PlanningState 转成 Python dict

            payload.update(patch)  # 用节点 patch 更新当前状态 dict

            current = PlanningState.model_validate(payload)  # 把更新后的 dict 校验并转换回 PlanningState

            yield sse_event(  # 发送 agent 思考过程事件
                "agent_thinking",  # SSE 事件名
                build_agent_thinking_payload(  # 构造前端可展示的 agent 思考 payload
                    node_name,  # 当前完成的节点名
                    patch,  # 当前节点产生的状态变化
                    current.model_dump(mode="json"),  # 当前完整状态，转成 JSON 兼容格式
                ),
            )

            yield sse_event(  # 发送节点完成事件
                "node_update",  # SSE 事件名
                {
                    "node": node_name,  # 当前完成的节点
                    "message": f"{node_name} completed",  # 节点完成提示
                    "duration_ms": 0,  # 节点耗时，这里暂时写死为 0
                },
            )

    legacy = planning_state_to_legacy(current)  # 图执行结束后，把最终 V2 状态转成旧版兼容 dict

    legacy["session_id"] = session_id  # 补充 session_id

    response = build_trip_response(legacy, include_debug=request.debug)  # 构造 TripPlanResponse

    for chunk in chunk_text(response.response_text):  # 将最终文本切成小块，模拟逐字/逐段流式输出
        yield sse_event("response_chunk", {"delta": chunk})  # 发送文本增量事件

    yield sse_event("final", response.model_dump())  # 发送最终完整响应事件

    yield sse_event("done", {"ok": True})  # 发送结束事件


def build_trip_response(result: dict[str, Any], *, include_debug: bool = False) -> TripPlanResponse:
    result = attach_frontend_compatibility(result)  # 给结果补充前端兼容字段，比如 weather、routes

    return TripPlanResponse(  # 构造标准 API 响应对象
        response_text=result.get("response_text", ""),  # 主响应文本
        execution_status=result.get("execution_status", "unknown"),  # 执行状态，没有则 unknown
        intent_type=result.get("intent_type", ""),  # 意图类型
        answer_mode=result.get("answer_mode", ""),  # 回答模式
        need_clarification=False,  # V2 当前默认不追问
        selected_plan=result.get("selected_plan", {}),  # 当前选中的方案
        ranked_plans=result.get("ranked_plans", []),  # 排序后的候选方案列表
        errors=result.get("errors", []),  # 错误列表
        logs=result.get("logs", []),  # 日志列表
        session_id=result.get("session_id", ""),  # 会话 ID
        trace_id=result.get("trace_id", ""),  # trace ID
        run_id=result.get("run_id", ""),  # run ID
        revision_id=result.get("revision_id", ""),  # 修订 ID
        is_revision=bool(result.get("is_revision", False)),  # 是否为修订请求
        task_id=result.get("task_id", ""),  # 任务 ID
        final_text=result.get("final_text") or result.get("response_text", ""),  # 最终文本，优先 final_text，否则用 response_text
        response_payload=result.get("response_payload", {}),  # 面向前端的结构化响应数据
        plan_state_id=result.get("plan_state_id", ""),  # 规划状态 ID
        constraints=result.get("constraints", {}),  # 约束条件，比如城市、预算、距离、人数等
        target_categories=result.get("target_categories", []),  # 目标 POI 类别
        weather=result.get("weather", {}),  # 天气信息
        routes=result.get("routes", []),  # 路线信息
        debug=result.get("debug", {}) if include_debug else {},  # 如果开启 debug，就返回调试信息，否则为空
    )


def attach_frontend_compatibility(result: dict[str, Any]) -> dict[str, Any]:
    ranked = [  # 构造 ranked_plans 的浅拷贝列表，避免直接修改原对象
        dict(plan)  # 将每个 plan 拷贝成新 dict
        for plan in result.get("ranked_plans", [])  # 遍历结果中的 ranked_plans
        if isinstance(plan, dict)  # 只处理 dict 类型的 plan
    ]

    selected = dict(result.get("selected_plan") or {})  # 拷贝 selected_plan，没有则为空 dict

    if not ranked and not selected:  # 如果既没有候选方案，也没有选中方案
        return result  # 直接返回原结果，不补充天气和路线

    city = str((result.get("constraints") or {}).get("city") or "北京")  # 从 constraints 中取城市，没有则默认北京

    weather = AmapWeatherService().current_weather(city)  # 调用高德天气服务获取当前城市天气

    ranked = [{**plan, "weather": weather} for plan in ranked]  # 给每个候选方案补充 weather 字段

    if selected:  # 如果存在选中方案
        selected["weather"] = weather  # 给选中方案也补充 weather 字段

    routes = [  # 构造前端需要的 routes 列表
        {
            "plan_id": plan.get("id") or plan.get("plan_id"),  # 方案 ID，兼容 id 和 plan_id
            "segments": plan.get("route_segments", []),  # 路线分段
        }
        for plan in ranked  # 遍历每个候选方案
    ]

    return {  # 返回补充前端字段后的新结果
        **result,  # 保留原 result 中的字段
        "ranked_plans": ranked,  # 覆盖 ranked_plans
        "selected_plan": selected,  # 覆盖 selected_plan
        "weather": weather,  # 顶层补充 weather
        "routes": routes,  # 顶层补充 routes
    }


def checkpoint_status_from_state(state: dict[str, Any]) -> TaskStatus:
    if state.get("selected_plan") or state.get("ranked_plans"):  # 如果已经有选中方案或候选方案
        return TaskStatus.PLAN_VALIDATED  # 认为任务已完成方案验证

    if state.get("response_text"):  # 如果已经有响应文本，但没有方案
        return TaskStatus.INTENT_PARSED  # 认为至少完成了意图解析或文本生成

    return TaskStatus.CREATED  # 否则认为任务仍是刚创建状态


def effective_query_for_request(saved_session: dict[str, Any] | None, current_query: str) -> str:
    """V2 不拼接旧 query；会话摘要由 session_state_loader 读取。"""

    return current_query  # V2 直接使用当前 query，不再把历史 query 拼接进去


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"  # 按 SSE 协议格式拼接事件字符串


def chunk_text(text: str, chunk_size: int = 18) -> Iterator[str]:
    for index in range(0, len(text or ""), chunk_size):  # 每次按 chunk_size 步长遍历文本
        yield text[index : index + chunk_size]  # 返回当前文本片段
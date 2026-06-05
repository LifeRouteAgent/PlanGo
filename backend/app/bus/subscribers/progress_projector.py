from __future__ import annotations

from typing import Any

from app.bus.event import Event
from app.streaming.schemas import FrontendProgressEvent

NODE_STARTED_MESSAGES: dict[str, tuple[str, str]] = {
    "request_context_loader": ("正在整理请求", "正在读取位置、会话和可用数据目录。"),
    "session_state_loader": ("正在读取会话", "正在参考上一轮方案和约束。"),
    "memory_reader": ("正在读取偏好", "正在整理你过往表达过的偏好。"),
    "intent_resolver": ("正在理解你的需求", "正在识别人群、时间、距离、预算和地点偏好。"),
    "constraint_builder": ("正在补齐规划约束", "正在合并默认值、预算、距离和时间要求。"),
    "recall_plan_compiler": ("正在生成查询计划", "正在把需求转换成安全的候选召回计划。"),
    "collector": ("正在查找候选地点", "正在查找符合距离、标签和关键词要求的地点。"),
    "poi_scorer": ("正在给地点打分", "正在根据距离、标签、关键词和质量排序候选。"),
    "candidate_pool_balancer": ("正在平衡候选池", "正在保留更多不同类别、价格和距离的选择。"),
    "route_planner": ("正在组合路线", "正在把地点组合成时间顺、少绕路的方案。"),
    "pre_ranker": ("正在初排方案", "正在先筛出更值得检查的候选方案。"),
    "availability_checker": ("正在检查可用性", "正在检查营业、预约、排队和库存风险。"),
    "post_check_filter": ("正在过滤不可用方案", "正在移除明确不可执行的方案。"),
    "failure_analyzer": ("正在分析方案不足原因", "正在判断是否需要放宽非核心条件。"),
    "fallback_relaxation": ("已适度放宽条件", "附近候选较少，正在放宽部分非核心条件继续规划。"),
    "final_ranker": ("正在排序方案", "正在根据距离、预算、时间和可执行性排序。"),
    "response_assembler": ("正在整理展示信息", "正在生成前端可展示的方案卡片。"),
    "response_generator": ("正在生成最终回复", "正在基于已确认的方案生成对话回复。"),
    "session_state_saver": ("正在保存会话", "正在保存本次约束摘要和方案结果。"),
}

BUSINESS_MESSAGES: dict[str, tuple[str, str, str]] = {
    "run_started": ("progress", "规划已启动", "正在开始处理你的规划请求。"),
    "intent_parsed": ("progress", "已理解你的需求", "已识别请求类型、目标地点类型和主要约束。"),
    "slots_generated": ("progress", "已生成行程结构", "已拆分出需要安排的行程环节。"),
    "recall_plan_created": ("progress", "已生成查询计划", "接下来会按类别查找候选地点。"),
    "poi_recalled": ("progress", "已找到候选地点", "已找到候选地点，正在继续筛选和排序。"),
    "poi_scored": ("progress", "已完成地点打分", "已按距离、标签、关键词和质量完成初筛。"),
    "poi_filtered": ("progress", "已平衡候选池", "已保留更多不同类别、价格和距离的候选。"),
    "plan_generated": ("progress", "已生成初步方案", "已组合出初步方案，正在检查可执行性。"),
    "plan_validated": ("progress", "已检查方案可用性", "已检查营业、预约、排队和库存风险。"),
    "plan_ranked": ("progress", "已完成方案排序", "已选出当前最合适的候选方案。"),
    "constraint_relaxed": ("warning", "已适度放宽条件", "候选不足，已在不违背核心需求的前提下放宽条件。"),
    "plan_insufficient": ("warning", "方案数量不足", "当前可用方案较少，系统正在尝试放宽非核心条件。"),
    "partial_result_used": ("warning", "使用部分结果", "部分信息不可用，系统会用已确认的信息继续规划。"),
    "tool_failed": ("warning", "部分信息暂时不可用", "部分工具查询失败，系统正在使用可用信息继续规划。"),
    "run_finished": ("final", "规划完成", "已生成可执行方案。"),
    "run_failed": ("error", "规划暂时失败", "规划过程中出现问题，请稍后重试或放宽条件。"),
}


class ProgressProjector:
    """Project internal Event into user-readable frontend progress."""

    def project(self, event: Event) -> FrontendProgressEvent | None:
        if event.event_type == "node_started" and event.node_name:
            title, message = NODE_STARTED_MESSAGES.get(
                event.node_name,
                ("正在处理规划步骤", "系统正在继续处理你的规划请求。"),
            )
            return self._progress(event, title, message, "running", step=event.node_name)

        if event.event_type == "node_failed":
            return self._progress(
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
            return self._progress(
                event,
                title,
                _format_message(message, data),
                status,
                step=event.node_name,
                event_type=frontend_type,
                data=data,
            )
        return None

    def _progress(
        self,
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


def _status_for(event_type: str, frontend_type: str) -> str:
    if frontend_type == "error":
        return "failed"
    if frontend_type == "warning":
        return "warning"
    if event_type == "run_finished":
        return "success"
    return "running" if event_type not in {"intent_parsed", "slots_generated", "plan_ranked"} else "success"


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

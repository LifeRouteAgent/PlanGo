from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.routes.trip import stream_plan_trip
from app.models.schemas import TripPlanRequest
from app.services.memory_service import MemoryService
from app.services.trace_recorder import record_trace_event

router = APIRouter(prefix="/api", tags=["compat"])


@router.get("/cities")
def list_cities() -> dict[str, list[dict[str, str]]]:
    """兼容旧前端的城市列表接口。

    当前项目以本地生活规划为主，真实城市和区域约束主要来自用户画像、本地数据库和本轮输入。
    这里返回稳定的 demo 城市列表，避免旧页面或浏览器缓存仍请求 /api/cities 时出现 404。
    """

    return {
        "cities": [
            {"code": "beijing", "name": "北京"},
            {"code": "shanghai", "name": "上海"},
            {"code": "guangzhou", "name": "广州"},
            {"code": "shenzhen", "name": "深圳"},
            {"code": "hangzhou", "name": "杭州"},
            {"code": "chengdu", "name": "成都"},
        ]
    }


@router.get("/user/profile")
def get_user_profile(user_id: str = Query(default="default")) -> dict[str, Any]:
    """兼容旧前端的用户画像接口，复用现有 MemoryService。"""

    return MemoryService().profile_payload(user_id=user_id)


def _extract_user_query(payload: dict[str, Any]) -> str:
    """从不同前端版本的请求体里提取用户输入。

    新后端标准字段是 user_query，但旧页面可能发送 query/input/message/text/userMessage。
    这里做一次兼容映射，避免 FastAPI 因缺少 user_query 直接返回 422。
    """

    for key in ("user_query", "query", "input", "message", "userMessage", "text", "prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    messages = payload.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            if not isinstance(item, dict):
                continue
            content = item.get("content") or item.get("text")
            if isinstance(content, str) and content.strip():
                return content.strip()

    return ""


@router.post("/plan-stream")
def compat_plan_stream(payload: dict[str, Any] = Body(default_factory=dict)) -> StreamingResponse:
    """兼容旧前端的流式规划接口，转发到 /trip/plan/stream。

    注意：这个接口只做字段归一化，不复制规划逻辑；真正的 LangGraph DAG 仍然只在 trip 路由中维护。
    """

    user_query = _extract_user_query(payload)
    if not user_query:
        raise HTTPException(
            status_code=400, detail="请求体缺少用户输入，请传 user_query、query、input 或 message。"
        )

    user_profile = payload.get("user_profile") or payload.get("profile") or {}
    if not isinstance(user_profile, dict):
        user_profile = {}

    max_replanning_count = payload.get("max_replanning_count", payload.get("maxReplanningCount", 2))
    try:
        max_replanning_count = int(max_replanning_count)
    except (TypeError, ValueError):
        max_replanning_count = 2

    request = TripPlanRequest(
        user_query=user_query,
        user_profile=user_profile,
        max_replanning_count=max_replanning_count,
        session_id=payload.get("session_id") or payload.get("sessionId"),
        trace_id=payload.get("trace_id") or payload.get("traceId"),
        run_id=payload.get("run_id") or payload.get("runId"),
    )
    return stream_plan_trip(request)


@router.post("/plans/{plan_id}/{action}")
def compat_plan_action(plan_id: str, action: str) -> dict[str, Any]:
    """兼容前端的方案操作接口。

    前端历史版本会调用 `/api/plans/{planId}/{action}` 处理保存、收藏、分享、加入日历、
    导航和模拟预订。正式执行流仍走 `/trip/execute/stream`；这里仅返回稳定的轻量结果，
    避免前后端接口不一致导致按钮报错。
    """

    allowed = {"save", "favorite", "share", "book", "calendar", "navigate"}
    if action not in allowed:
        raise HTTPException(status_code=404, detail=f"不支持的方案操作：{action}")

    record_trace_event(
        "compat_plan_action",
        {
            "plan_id": plan_id,
            "action": action,
            "source": "api_compat",
        },
    )
    base_plan = {
        "id": plan_id,
        "saved": action == "save",
        "favorited": action == "favorite",
        "actions": [],
        "route": {"segments": [], "stops": []},
    }
    if action == "save":
        return {"plan": base_plan, "saved": True}
    if action == "favorite":
        return {"plan": base_plan, "favorited": True}
    if action == "share":
        return {
            "share_id": f"share-{plan_id}",
            "share_url": f"/share/{plan_id}",
            "share_message": "这是我生成的本地生活方案。",
        }
    if action == "calendar":
        return {
            "calendar_event_id": f"calendar-{plan_id}",
            "title": "本地生活方案",
            "start_time": "",
            "end_time": "",
            "status": "created",
        }
    if action == "navigate":
        return base_plan["route"]
    return {
        "plan": {
            **base_plan,
            "actions": [
                {
                    "id": f"mock-book-{plan_id}",
                    "type": "mock_booking",
                    "status": "confirmed",
                    "order_id": f"MOCK-{plan_id}",
                }
            ],
        },
        "actions": [
            {
                "id": f"mock-book-{plan_id}",
                "type": "mock_booking",
                "status": "confirmed",
                "order_id": f"MOCK-{plan_id}",
            }
        ],
    }

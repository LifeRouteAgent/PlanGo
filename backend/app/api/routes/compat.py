from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse

from app.api.routes.trip import stream_plan_trip
from app.api.schemas.trip import TripPlanRequest
from app.integrations.amap_weather_service import get_amp_weather_service
from app.memory.memory_event_queue import MemoryEventQueue
from app.memory.memory_service import MemoryService
from app.repositories.poi_repository import PoiRepository
from app.observability.trace_recorder import TraceRecorder
from app.repositories.constants import (
    POI_ATTRACTION,
    POI_SHOPPING,
    POI_ACTIVITY,
    POI_RESTAURANT,
    POI_FITNESS,
    POI_ENTERTAINMENT,
    POI_BEAUTY,
    POI_CATEGORIES,
)

router = APIRouter(prefix="/api", tags=["compat"])


@router.get("/cities")
def list_cities() -> dict[str, list[dict[str, str]]]:
    """兼容旧前端的城市列表接口。

    当前产品主要支持北京本地生活规划，其他城市仅作为前端筛选占位。
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
    """兼容旧前端的用户画像接口，复用当前 MemoryService。"""

    return MemoryService().profile_payload(user_id=user_id)


@router.get("/home/inspirations")
def home_inspirations(
    limit: int = Query(default=8, ge=1, le=20)
) -> dict[str, list[dict[str, Any]]]:
    """首页灵感推荐。

    不写死 POI，而是从本地数据库按类别混合取带图片的地点，用于首页右侧灵感卡片。
    完整规划仍由 LangGraph DAG 负责；这里仅返回轻量展示数据。
    """

    categories = list(POI_CATEGORIES)
    result = PoiRepository().fetch_by_categories(categories)
    items: list[dict[str, Any]] = []
    max_category_len = max((len(result.get(category, [])) for category in categories), default=0)

    for index in range(max_category_len):
        for category in categories:
            category_items = result.get(category, [])
            if index >= len(category_items):
                continue
            poi = category_items[index]
            image_url = poi.get("image_url") or (poi.get("images") or [None])[0]
            if not image_url:
                continue
            tag = (
                poi.get("tags")
                or [poi.get("subcategory") or _home_category_label(str(poi.get("category") or ""))]
            )[0]
            if not tag:
                tag = _home_category_label(str(poi.get("category") or ""))
            items.append({
                "id": poi.get("id"),
                "name": poi.get("name"),
                "category": poi.get("category"),
                "tag": tag,
                "tags": poi.get("tags") or [],
                "image_url": image_url,
                "duration_text": _home_duration_text(str(poi.get("category") or "")),
            })
            if len(items) >= limit:
                return {"items": items}
    return {"items": items}


@router.get("/home/weather")
def home_weather(amap_weather_service=Depends(get_amp_weather_service)) -> dict[str, Any]:
    """首页侧边栏天气。当前产品仅支持北京，因此固定读取北京实时天气。"""
    weather = amap_weather_service.current_weather("beijing")
    return {"city": "北京", "supported_scope": "目前仅支持北京", "weather": weather}


def _home_duration_text(category: str) -> str:
    if category == POI_RESTAURANT:
        return "1-2h"
    if category == POI_ENTERTAINMENT:
        return "2-3h"
    if category == POI_ACTIVITY:
        return "2-4h"
    if category == POI_ATTRACTION:
        return "2-4h"
    if category == POI_SHOPPING:
        return "1-3h"
    if category == POI_FITNESS:
        return "1-2h"
    if category == POI_BEAUTY:
        return "1-2h"
    return "1-3h"


def _home_category_label(category: str) -> str:
    return {
        POI_ATTRACTION: "景点",
        POI_SHOPPING: "购物",
        POI_ACTIVITY: "活动",
        POI_RESTAURANT: "餐厅",
        POI_FITNESS: "健身",
        POI_ENTERTAINMENT: "娱乐",
        POI_BEAUTY: "养生",
    }.get(category, "本地生活")


@router.post("/mock/restaurant-booking")
def mock_restaurant_booking(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _mock_action_response(
        "restaurant_booking", payload, order_prefix="REST", message="餐厅预约已确认"
    )


@router.post("/mock/ticket-reservation")
def mock_ticket_reservation(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _mock_action_response(
        "ticket_reservation", payload, order_prefix="TICKET", message="票务名额已锁定"
    )


@router.post("/mock/taxi-dispatch")
def mock_taxi_dispatch(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _mock_action_response(
        "taxi_dispatch", payload, order_prefix="TAXI", message="打车路线已准备"
    )


@router.post("/mock/calendar-event")
def mock_calendar_event(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    return _mock_action_response(
        "calendar_event", payload, order_prefix="CAL", message="日历提醒已生成"
    )


def _mock_action_response(
    action_type: str,
    payload: dict[str, Any],
    *,
    order_prefix: str,
    message: str,
) -> dict[str, Any]:
    time.sleep(2000)
    plan_id = str(payload.get("plan_id") or "")
    target_id = str(payload.get("target_id") or payload.get("action_id") or "")
    target_name = str(payload.get("target_name") or payload.get("title") or "PlanGo 目标")
    order_id = f"{order_prefix}-{uuid4().hex[:10].upper()}"
    result = {
        "ok": True,
        "action_type": action_type,
        "action_id": str(payload.get("action_id") or f"{action_type}-{uuid4().hex[:8]}"),
        "plan_id": plan_id,
        "target_id": target_id,
        "target_name": target_name,
        "status": "confirmed",
        "order_id": order_id,
        "message": message,
        "created_at": int(time.time()),
        "mock": True,
    }
    TraceRecorder.record(
        "mock_api_called",
        {
            "action_type": action_type,
            "plan_id": plan_id,
            "target_id": target_id,
            "order_id": order_id,
        },
    )
    return result


def _extract_user_query(payload: dict[str, Any]) -> str:
    """从不同前端版本的请求体里提取用户输入。

    标准字段是 user_query，但旧页面可能发送 query/input/message/text/userMessage。
    这里做字段归一化，避免旧入口因为缺少 user_query 直接返回 422。
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
    """兼容旧前端的流式规划入口，转发到 /trip/plan/stream。

    该接口只做字段归一化，不复制规划逻辑；真正的 LangGraph DAG 仍在 trip 路由中维护。
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
    except TypeError, ValueError:
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
    """兼容前端轻量方案操作入口。

    正式执行流仍走 /trip/execute/stream；这里仅用于保存、收藏、分享、日历、导航和 mock 预订按钮的兼容返回。
    """

    allowed = {"save", "favorite", "share", "book", "calendar", "navigate"}
    if action not in allowed:
        raise HTTPException(status_code=404, detail=f"不支持的方案操作：{action}")

    TraceRecorder.record(
        "compat_plan_action",
        {
            "plan_id": plan_id,
            "action": action,
            "source": "api_compat",
        },
    )
    stage = {
        "save": "plan_saved",
        "favorite": "plan_favorited",
        "book": "plan_selected",
        "calendar": "plan_exported_calendar",
    }.get(action)
    if stage:
        MemoryEventQueue().publish_plan_feedback(
            {"id": plan_id, "plan_id": plan_id, "title": f"Plan {plan_id}", "items": []},
            user_id="default",
            stage=stage,
            feedback={"source": "api_compat", "action": action},
            session_id="default",
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
            "share_message": "这是我用 PlanGo 生成的本地生活方案。",
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
            "actions": [{
                "id": f"mock-book-{plan_id}",
                "type": "mock_booking",
                "status": "confirmed",
                "order_id": f"MOCK-{plan_id}",
            }],
        },
        "actions": [{
            "id": f"mock-book-{plan_id}",
            "type": "mock_booking",
            "status": "confirmed",
            "order_id": f"MOCK-{plan_id}",
        }],
    }

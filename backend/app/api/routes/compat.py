from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.api.routes.trip import stream_plan_trip
from app.models.schemas import TripPlanRequest
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/api", tags=["compat"])


@router.get("/cities")
def list_cities() -> dict[str, list[dict[str, str]]]:
    """兼容旧前端的城市列表接口。

    当前项目以本地生活规划为主，默认城市来自用户画像和本地数据库配置。这里返回稳定的
    demo 城市列表，避免旧页面或缓存仍请求 /api/cities 时出现 404。
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


@router.post("/plan-stream")
def compat_plan_stream(request: TripPlanRequest) -> StreamingResponse:
    """兼容旧前端的流式规划接口，转发到 /trip/plan/stream。"""

    return stream_plan_trip(request)

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TripPlanRequest(BaseModel):
    user_query: str = Field(..., min_length=1)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    max_replanning_count: int = Field(default=2, ge=0, le=3)


class TripPlanResponse(BaseModel):
    response_text: str
    execution_status: str
    intent_type: str = ""
    answer_mode: str = ""
    need_clarification: bool = False
    missing_constraints: list[str] = Field(default_factory=list)
    clarify_question: str = ""
    selected_plan: dict[str, Any]
    ranked_plans: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    logs: list[str]


class ExecutePlanRequest(BaseModel):
    plan: dict[str, Any]


class ExportPlanRequest(BaseModel):
    plan: dict[str, Any]


class AdjustPlanRequest(BaseModel):
    """方案局部调整请求。

    前端用于“某一站不满意，换一个类似地点”的产品化调整。
    不要求重新跑完整 DAG，后端会按当前站点类别从数据库找替代 POI。
    """

    plan: dict[str, Any]
    poi_id: str
    prompt: str = Field(default="换一个更合适的")


class DataSourceStatusResponse(BaseModel):
    enabled: bool
    source: str
    database_name: str
    table_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None

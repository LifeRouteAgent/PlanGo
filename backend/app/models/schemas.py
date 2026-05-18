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


class DataSourceStatusResponse(BaseModel):
    enabled: bool
    source: str
    database_name: str
    table_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None

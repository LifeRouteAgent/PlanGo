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
    selected_plan: dict[str, Any]
    ranked_plans: list[dict[str, Any]]
    errors: list[str]
    logs: list[str]

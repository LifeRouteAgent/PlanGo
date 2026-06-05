from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ProgressStatus = Literal["pending", "running", "success", "warning", "failed"]


class FrontendProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "progress"
    title: str
    message: str
    status: ProgressStatus = "running"
    step: str | None = None
    request_id: str
    run_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = Field(default_factory=dict)

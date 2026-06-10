from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProgressStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    WARNING = "warning"
    FAILED = "failed"


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

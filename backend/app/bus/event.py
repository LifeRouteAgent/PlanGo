from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    RUN_FINISHED = "run_finished"
    RUN_FAILED = "run_failed"
    NODE_STARTED = "node_started"
    NODE_FAILED = "node_failed"
    INTENT_PARSED = "intent_parsed"
    SLOTS_GENERATED = "slots_generated"
    RECALL_PLAN_CREATED = "recall_plan_created"
    POI_RECALLED = "poi_recalled"
    POI_SCORED = "poi_scored"
    POI_FILTERED = "poi_filtered"
    PLAN_GENERATED = "plan_generated"
    PLAN_VALIDATED = "plan_validated"
    PLAN_RANKED = "plan_ranked"
    CONSTRAINT_RELAXED = "constraint_relaxed"
    PLAN_INSUFFICIENT = "plan_insufficient"
    PARTIAL_RESULT_USED = "partial_result_used"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"


FORBIDDEN_PAYLOAD_KEYS = {
    "api_key",
    "authorization",
    "chain_of_thought",
    "cot",
    "password",
    "prompt",
    "raw_json",
    "raw_output",
    "secret",
    "sql",
    "stack",
    "stacktrace",
    "traceback",
    "token",
}
# 限制 payload 长度, 避免无限递归导致程序卡死
MAX_PAYLOAD_KEYS = 20
MAX_STRING_LENGTH = 300
MAX_LIST_PREVIEW = 5


class Event(BaseModel):
    """Internal runtime event.

    EventBus broadcasts this object, but frontend code must consume only the
    projected FrontendProgressEvent produced by ProgressProjector.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    event_type: EventType
    request_id: str
    run_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None
    node_name: str | None = None
    agent_name: str | None = None
    tool_name: str | None = None
    status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    sequence: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_ref: str | None = None

    @classmethod
    # 这个装饰器让它被 Pydantic 框架自动调用——每次创建 Event 对象时,
    # Pydantic 会在赋值 payload 字段之前先跑这个函数做清洗
    @field_validator("payload", mode="before")
    def sanitize_payload(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"summary": _safe_value(value)}
        return {
            str(key)[:80]: _safe_value(item)
            for key, item in list(value.items())[:MAX_PAYLOAD_KEYS]
            if str(key).lower() not in FORBIDDEN_PAYLOAD_KEYS
        }


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if any(token in lowered for token in ("select ", "traceback", "api_key", "bearer ")):
            return "[redacted]"
        return text[:MAX_STRING_LENGTH]
    if isinstance(value, list | tuple | set):
        values = list(value)
        preview = [_safe_value(item) for item in values[:MAX_LIST_PREVIEW]]
        return {"count": len(values), "preview": preview}
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_PAYLOAD_KEYS]:
            key_text = str(key)
            if key_text.lower() in FORBIDDEN_PAYLOAD_KEYS:
                continue
            safe[key_text[:80]] = _safe_value(item)
        if len(value) > MAX_PAYLOAD_KEYS:
            safe["truncated_key_count"] = len(value) - MAX_PAYLOAD_KEYS
        return safe
    return str(value)[:MAX_STRING_LENGTH]

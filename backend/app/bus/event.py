from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    event_type: str
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

    @field_validator("payload", mode="before")
    @classmethod
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

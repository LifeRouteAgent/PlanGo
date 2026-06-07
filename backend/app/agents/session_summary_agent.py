from __future__ import annotations

import json
from typing import Any

from app.llm.llm_client import call_chat_completion, extract_json_object
from app.llm.output_schemas import SessionSummaryOutput, validate_llm_output
from app.llm.prompt_registry import load_prompt_template
from app.observability.trace_recorder import record_trace_event


def compress_session_summary(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Use LLM to compress session context into structured summary JSON."""

    raw = call_chat_completion(
        [
            {
                "role": "system",
                "content": load_prompt_template(
                    "session_summary",
                    "You are a structured session context compressor. Output JSON only.",
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.0,
        timeout_seconds=30,
        max_completion_tokens=1200,
        prompt_name="session_summary",
        schema_name="SessionSummaryOutput",
    )
    parsed = extract_json_object(raw)
    validation = (
        validate_llm_output(SessionSummaryOutput, parsed, source="session_summary")
        if isinstance(parsed, dict)
        else None
    )
    record_trace_event(
        "session_summary_compressed",
        {
            "success": bool(validation and validation.ok),
            "raw_preview": str(raw or "")[:600],
        },
    )
    return validation.data if validation and validation.ok else None

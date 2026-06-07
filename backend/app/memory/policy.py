from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LONG_TERM_CONFIDENCE_THRESHOLD = 0.65

TEMPORARY_SCOPE = "temporary"
LONG_TERM_SCOPE = "long_term"

SENSITIVE_HINTS = (
    "手机号",
    "身份证",
    "住址",
    "地址",
    "公司",
    "学校",
    "收入",
    "疾病",
)


@dataclass(frozen=True)
class MemoryWriteDecision:
    should_update_profile: bool
    scope: str
    confidence: float
    reason: str


class MemoryPolicy:
    """Centralizes memory write rules without changing the planning graph."""

    def stage_weight(self, stage: str) -> float:
        return {
            "user_query": 0.4,
            "plan_saved": 0.8,
            "plan_favorited": 1.0,
            "plan_exported_pdf": 1.1,
            "plan_exported_calendar": 1.1,
            "plan_selected": 1.6,
            "plan_executed": 2.2,
        }.get(stage, 1.2)

    def decide_extracted_profile_update(
        self, extracted: dict[str, Any] | None
    ) -> MemoryWriteDecision:
        if not extracted:
            return MemoryWriteDecision(False, TEMPORARY_SCOPE, 0.0, "no_extraction")
        confidence = _safe_float(extracted.get("confidence"), 0.0)
        scope = str(extracted.get("scope") or TEMPORARY_SCOPE)
        if scope != LONG_TERM_SCOPE:
            return MemoryWriteDecision(False, scope, confidence, "not_long_term")
        if confidence < LONG_TERM_CONFIDENCE_THRESHOLD:
            return MemoryWriteDecision(False, scope, confidence, "low_confidence")
        if not extracted.get("should_update_profile"):
            return MemoryWriteDecision(False, scope, confidence, "extractor_rejected")
        return MemoryWriteDecision(True, scope, confidence, "accepted")

    def sanitize_terms(self, values: list[str], *, limit: int = 16) -> list[str]:
        return [
            value
            for value in _dedupe(str(item).strip() for item in values if str(item).strip())
            if not any(hint in value for hint in SENSITIVE_HINTS)
        ][:limit]

    def should_record_negative_feedback(self, stage: str, feedback: dict[str, Any] | None) -> bool:
        if stage in {"plan_rejected", "negative_feedback"}:
            return True
        message = str((feedback or {}).get("reason") or (feedback or {}).get("message") or "")
        return any(marker in message for marker in ("以后", "长期", "总是", "再也不", "不要推荐"))


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except TypeError, ValueError:
        return fallback


def _dedupe(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result

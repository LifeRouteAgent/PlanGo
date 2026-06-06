from __future__ import annotations

from app.agents.intent_agent import build_llm_understanding
from app.llm.output_schemas import IntentUnderstandingOutput, validate_llm_output


def test_intent_understanding_schema_rejects_invalid_shape() -> None:
    result = validate_llm_output(
        IntentUnderstandingOutput,
        {"intent_type": "full_trip_plan", "people_count": 0},
        source="test",
    )

    assert result.ok is False
    assert result.schema_name == "IntentUnderstandingOutput"


def test_intent_understanding_agent_returns_none_when_llm_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.intent_agent.call_chat_completion", lambda *_, **__: "")

    assert build_llm_understanding("周末想出去玩", {}, conversation_context={}) is None

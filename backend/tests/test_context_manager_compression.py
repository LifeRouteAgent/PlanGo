from __future__ import annotations

from app.context.context_manager import ContextManager, estimate_prompt_tokens


def test_context_manager_uses_llm_summary_when_triggered(monkeypatch) -> None:
    saved = {
        "latest_planning_state": {
            "intent_type": "full_trip_plan",
            "constraints": {"budget": 300, "avoid_keywords": ["hotpot"]},
        },
        "latest_planning_response": {"ranked_plans": [{"id": "plan_1"}]},
        "turns": [{"user_query": f"turn-{index}"} for index in range(9)],
    }

    monkeypatch.setattr(
        "app.context.context_manager.compress_session_summary",
        lambda payload: {
            "summary": "User is refining a relaxed low-budget plan.",
            "active_constraints": {"current_goal": "relaxed_plan"},
            "negative_constraints": ["too_far"],
            "resolved_references": {"selected_plan_id": "plan_1"},
            "current_focus": "adjust_route",
            "last_plan_ids": ["plan_1"],
            "open_questions": [],
        },
    )

    summary = ContextManager().session_summary(saved)

    assert summary.summary == "User is refining a relaxed low-budget plan."
    assert summary.active_constraints["budget"] == 300
    assert summary.active_constraints["current_goal"] == "relaxed_plan"
    assert summary.negative_constraints == ["hotpot", "too_far"]
    assert summary.current_focus == "adjust_route"


def test_context_manager_trims_prompt_pack_over_budget() -> None:
    raw_pack = {
        "session_summary": {},
        "recent_turns": [
            {"role": "user", "content": "long-context" * 800}
            for _ in range(10)
        ],
        "last_plan_snapshot": {"last_plan_ids": ["p1", "p2", "p3", "p4"]},
        "memory_context": {
            "positive_tags": [
                {"tag_id": f"tag_{index}", "tag_name": "preference" * 100, "confidence": 0.8}
                for index in range(20)
            ],
            "negative_tags": [
                {"tag_id": f"neg_{index}", "tag_name": "avoid" * 100, "confidence": 0.8}
                for index in range(20)
            ],
            "similar_profiles": [
                {"cluster_id": f"c_{index}", "core_tags": ["x" * 100], "similarity_score": 0.8}
                for index in range(5)
            ],
        },
    }

    trimmed = ContextManager().trim_prompt_context_pack(raw_pack)

    assert estimate_prompt_tokens(raw_pack) > 6000
    assert trimmed["prompt_context_meta"]["trimmed"] is True
    assert len(trimmed["recent_turns"]) == 3
    assert len(trimmed["memory_context"]["positive_tags"]) == 6
    assert len(trimmed["memory_context"]["similar_profiles"]) == 2
    assert estimate_prompt_tokens(trimmed) < estimate_prompt_tokens(raw_pack)

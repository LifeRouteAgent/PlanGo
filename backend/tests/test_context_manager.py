from __future__ import annotations

from app.context.context_manager import ContextManager
from app.planning.state import ContextState, PreferenceCluster, PreferenceTag, UserPreferenceProfile


def test_context_manager_builds_structured_session_summary() -> None:
    saved = {
        "latest_planning_state": {
            "intent_type": "full_trip_plan",
            "constraints": {
                "scenario": "family",
                "budget": 500,
                "duration_minutes": 240,
                "preferred_categories": ["activity", "restaurant"],
                "avoid_keywords": ["too_far"],
            },
        },
        "latest_planning_response": {
            "response_payload": {"plans": [{"id": "plan_1"}, {"id": "plan_2"}, {"id": "plan_3"}]},
            "selected_plan": {"id": "plan_2"},
        },
        "turns": [{"user_query": "餐厅换便宜点"}],
    }

    summary = ContextManager().build_session_summary(saved)

    assert summary.summary
    assert summary.active_constraints["scenario"] == "family"
    assert summary.active_constraints["budget"] == 500
    assert summary.negative_constraints == ["too_far"]
    assert summary.current_focus == "replace_restaurant"
    assert summary.last_plan_ids == ["plan_1", "plan_2", "plan_3"]
    assert summary.resolved_references["selected_plan_id"] == "plan_2"


def test_context_manager_applies_session_payload_without_planning_decisions() -> None:
    saved = {
        "latest_planning_state": {
            "intent_type": "full_trip_plan",
            "constraints": {"city": "北京", "avoid_keywords": ["火锅"]},
        },
        "latest_planning_response": {
            "ranked_plans": [
                {"id": "plan_1"},
                {"id": "plan_2"},
                {"id": "plan_3"},
                {"id": "plan_4"},
            ],
            "selected_plan": {"id": "plan_1"},
        },
        "turns": [{"user_query": f"turn-{index}"} for index in range(8)],
    }

    context = ContextManager().apply_session_payload(ContextState(), saved)

    assert context.current_plan_state.has_active_plan is True
    assert context.current_plan_state.last_request_type == "full_trip_plan"
    assert len(context.current_plan_state.last_ranked_plans) == 3
    assert len(context.conversation_context.recent_turns) <= 5
    assert context.conversation_context.session_summary.negative_constraints == ["火锅"]
    assert "session_summary" in context.prompt_context_pack
    assert context.prompt_context_pack["last_plan_snapshot"]["last_plan_ids"] == [
        "plan_1",
        "plan_2",
        "plan_3",
    ]


def test_context_manager_prompt_pack_keeps_memory_as_soft_context() -> None:
    context = ContextState()
    context.user_preference_profile = UserPreferenceProfile(
        positive_tags=[PreferenceTag(tag_id="KTV", tag_name="KTV", confidence=0.9)],
        negative_tags=[PreferenceTag(tag_id="火锅", tag_name="火锅", confidence=0.8)],
        positive_clusters=[
            PreferenceCluster(
                cluster_id="similar_1",
                cluster_name="similar_user_profile",
                core_tags=["室内", "KTV"],
                similarity_score=0.88,
            )
        ],
    )

    pack = ContextManager().build_prompt_context_pack(context)

    assert pack["memory_context"]["positive_tags"][0]["tag_name"] == "KTV"
    assert pack["memory_context"]["negative_tags"][0]["tag_name"] == "火锅"
    assert pack["memory_context"]["similar_profiles"][0]["core_tags"] == ["室内", "KTV"]

from __future__ import annotations

from app.context.context_builder import ContextBuilder


def test_context_builder_limits_memory_snippets() -> None:
    """LLM 上下文只注入少量记忆摘要，不塞完整历史。"""

    context = ContextBuilder().build_user_profile_context({
        "memory_profile": {
            "preferred_city": "北京",
            "favorite_categories": {"poi_entertainment": 5, "poi_restaurant": 2},
            "disliked_keywords": ["室外", "火锅"],
        },
        "memory_context": {
            "profile_summary": "偏室内、低预算",
            "snippets": [f"memory-{index}" for index in range(10)],
            "memory_fit_tags": [f"tag-{index}" for index in range(20)],
            "source": "milvus+file",
        },
        "similar_user_preferences": [{"summary": "相似用户喜欢KTV"} for _ in range(8)],
    })

    assert context["memory_context"]["snippets"] == [f"memory-{index}" for index in range(5)]
    assert len(context["memory_context"]["memory_fit_tags"]) == 12
    assert len(context["similar_user_preferences"]) == 3


def test_context_builder_state_context_excludes_full_tool_payloads() -> None:
    """状态上下文只输出候选统计，不输出完整 POI 列表。"""

    context = ContextBuilder().build_state_context({
        "user_query": "周末唱歌",
        "intent_type": "full_trip_plan",
        "constraints": {"budget": 200, "llm_understanding": {"large": "payload"}},
        "candidate_pois": {"poi_entertainment": [{"id": "1"}, {"id": "2"}]},
        "recommended_pois": {"lifestyle": [{"id": "3"}]},
        "ranked_plans": [{"id": "p1"}],
        "errors": [],
    })

    assert context["candidate_counts"] == {"poi_entertainment": 2}
    assert context["recommended_counts"] == {"lifestyle": 1}
    assert "llm_understanding" not in context["constraints"]
    assert "candidate_pois" not in context


def test_context_snapshot_preserves_hard_constraints_and_clips_pois() -> None:
    """ContextSnapshot 应保留硬约束，同时只给 LLM top-k 工具证据。"""

    state = {
        "user_query": "明天两个人去环球影城再唱歌，预算1000",
        "intent_type": "full_trip_plan",
        "target_categories": ["poi_attraction", "poi_entertainment"],
        "constraints": {
            "people_count": 2,
            "budget": 1000,
            "must_pois": [{"name": "北京环球度假区"}],
            "excluded_keywords": ["火锅"],
            "llm_understanding": {"large": "payload"},
        },
        "dag_plan": {"planning_template": "couple_date"},
        "candidate_pois": {
            "poi_entertainment": [
                {"id": str(index), "name": f"KTV-{index}", "score": 100 - index}
                for index in range(12)
            ]
        },
        "recommended_pois": {},
        "ranked_plans": [{"id": "plan_1"}],
        "errors": [],
    }

    snapshot = ContextBuilder().build_for("planner_agent", state, top_k_per_category=5)

    assert snapshot["user_constraints"]["hard_constraints"]["people_count"] == 2
    assert snapshot["user_constraints"]["hard_constraints"]["budget"] == 1000
    assert snapshot["user_constraints"]["negative_constraints"]["excluded_keywords"] == ["火锅"]
    assert len(snapshot["tool_evidence"]) == 1
    assert snapshot["tool_evidence"][0]["result_summary"]["candidate_counts"]["poi_entertainment"] == 12
    assert "llm_understanding" not in snapshot["user_constraints"]["hard_constraints"]


def test_merge_revision_into_intent_appends_negative_constraints() -> None:
    """多轮需求修正要合并到当前 intent，明确排除项不能丢。"""

    previous = {
        "hard_constraints": {"people_count": 2, "budget": 1000},
        "soft_preferences": {"preferences": ["唱歌"]},
        "negative_constraints": {"excluded_keywords": ["火锅"]},
    }
    revision = {
        "soft_preferences": {"preferences": ["KTV"]},
        "negative_constraints": {"excluded_keywords": ["室外"]},
    }

    merged = ContextBuilder.merge_revision_into_intent(previous, revision)

    assert merged["hard_constraints"]["people_count"] == 2
    assert merged["soft_preferences"]["preferences"] == ["KTV"]
    assert merged["negative_constraints"]["excluded_keywords"] == ["火锅", "室外"]

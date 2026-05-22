from __future__ import annotations

from app.services.context_builder import ContextBuilder


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

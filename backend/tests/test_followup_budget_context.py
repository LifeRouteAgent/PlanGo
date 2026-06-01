from __future__ import annotations

from app.agents.constraint_builder import _fallback_parse_budget, _resolve_budget
from app.services.session_store import SessionStore
from app.services.trip_services import effective_query_for_request


def test_budget_uses_llm_first_and_fallback_only_when_llm_missing() -> None:
    query = "明天和对象去环球影城，预算1k\n用户更正/补充（以后者为准）：预算是1000元"

    assert _resolve_budget("预算1k", {"budget": 1000}) == (1000, "llm")
    assert _fallback_parse_budget("预算1k") == 1000
    assert _fallback_parse_budget("预算 1 K") == 1000
    assert _fallback_parse_budget(query) == 1000


def test_followup_budget_reuses_latest_planning_state_after_simple_qa() -> None:
    store = SessionStore()
    session_id = "test_followup_budget_context"
    planning_state = {
        "user_query": "明天我想和对象去环球影城玩，然后再去唱歌，预算1k，帮我规划一下具体行程",
        "intent_type": "full_trip_plan",
        "answer_mode": "trip_plan",
        "ranked_plans": [],
        "candidate_plans": [],
        "candidate_pois": {"poi_attraction": [{"id": "universal"}]},
    }
    planning_response = {
        "response_text": "预算风险提示",
        "intent_type": "full_trip_plan",
        "answer_mode": "trip_plan",
        "ranked_plans": [],
        "selected_plan": {},
    }
    store.save_turn(
        session_id=session_id,
        trace_id="trace_plan",
        run_id="run_plan",
        user_query=planning_state["user_query"],
        state=planning_state,
        response=planning_response,
    )
    simple_state = {
        "user_query": "你是什么模型",
        "intent_type": "simple_qa",
        "answer_mode": "simple_qa",
    }
    store.save_turn(
        session_id=session_id,
        trace_id="trace_qa",
        run_id="run_qa",
        user_query="你是什么模型",
        state=simple_state,
        response={
            "response_text": "我是本地生活规划助手。",
            "intent_type": "simple_qa",
            "answer_mode": "simple_qa",
            "ranked_plans": [],
            "selected_plan": {},
        },
    )

    merged = effective_query_for_request(store.load(session_id), "预算是1000元，接着为我规划，其他需求不变")

    assert "环球影城" in merged
    assert "唱歌" in merged
    assert "预算是1000元" in merged

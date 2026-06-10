from __future__ import annotations

from app.api.main import run_planning_request


def test_v2_records_retry_or_failure_context_without_v1_replan_loop() -> None:
    """V2 不再依赖 V1 的 verifier -> planner 回环，失败原因只进入 debug 和响应 warnings。"""

    state = run_planning_request("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元")
    nodes = [trace.node for trace in state.debug.node_trace]

    assert "availability_checker" in nodes
    assert "final_ranker" in nodes
    assert state.response.response_payload["response_type"] in {
        "plan_cards",
        "plan_adjustment_result",
    }
    assert state.response.response_payload.get("plans") is not None
    assert "raw_candidates" not in state.response.response_payload

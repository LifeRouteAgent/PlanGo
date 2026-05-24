from __future__ import annotations

from app.api.routes.trip import _effective_query_for_request


def test_effective_query_merges_pending_clarification_reply() -> None:
    """上一轮正在追问时，下一句短回答应合并回原始规划需求。"""

    saved_session = {
        "latest_state": {
            "user_query": "明天我要和对象去环球影城玩，然后去唱歌，帮我规划一下",
            "need_clarification": True,
            "clarify_question": "还需要确认人数和预算。",
        },
        "latest_response": {"need_clarification": True},
    }

    effective = _effective_query_for_request(saved_session, "两个人，预算1000")

    assert "明天我要和对象去环球影城玩" in effective
    assert "补充信息：两个人，预算1000" in effective


def test_effective_query_keeps_new_request_when_not_waiting() -> None:
    """上一轮没有追问时，本轮输入仍应作为全新请求处理。"""

    saved_session = {
        "latest_state": {
            "user_query": "你支持什么功能",
            "need_clarification": False,
        },
        "latest_response": {"need_clarification": False},
    }

    assert _effective_query_for_request(saved_session, "两个人，预算1000") == "两个人，预算1000"

from __future__ import annotations

from app.api.routes.trip import _apply_revision_constraints
from app.services.calendar_service import build_plan_ics
from app.services.memory_service import MemoryService
from app.services.session_store import SessionStore
from app.services.trace_recorder import TraceRecorder, new_id


def test_revision_constraints_prefer_indoor_and_exclude_keywords() -> None:
    """用户中途说不要室外时，应转成可被 Collector/Skill 消费的结构化约束。"""

    state = {"constraints": {"max_route_minutes": 45}, "logs": []}

    _apply_revision_constraints(state, "不要室外了，今天太热，也不要火锅")

    constraints = state["constraints"]
    assert constraints["indoor_preferred"] is True
    assert "室外" in constraints["avoid_tags"]
    assert "公园" in constraints["avoid_tags"]
    assert constraints["excluded_keywords"]


def test_calendar_service_builds_valid_ics() -> None:
    """方案时间线应能导出为标准 VCALENDAR 文本。"""

    ics_text = build_plan_ics({
        "title": "朋友周末方案",
        "timeline": [{
            "title": "打麻将",
            "start_time": "10:00",
            "end_time": "12:00",
            "address": "测试地址",
        }],
    })

    assert "BEGIN:VCALENDAR" in ics_text
    assert "BEGIN:VEVENT" in ics_text
    assert "SUMMARY:1. 打麻将" in ics_text


def test_trace_recorder_writes_and_reads_events() -> None:
    """TraceRecorder 应按 trace_id 写入 JSONL，并能读回摘要。"""

    trace_id = new_id("trace_test")
    recorder = TraceRecorder(trace_id=trace_id, run_id="run_test", session_id="sess_test")

    result = recorder.time_node("unit_node", lambda: {"ranked_plans": [{"id": "p1"}]})
    trace = TraceRecorder.read(trace_id)

    assert result["ranked_plans"][0]["id"] == "p1"
    assert trace["summary"]["node_count"] >= 1
    assert any(event.get("node_name") == "unit_node" for event in trace["events"])


def test_session_store_saves_latest_state() -> None:
    """SessionStore 保存最近 PlanState，供下一轮 revise 读取。"""

    session_store = SessionStore()
    session_id = new_id("sess_test")

    session_store.save_turn(
        session_id=session_id,
        trace_id="trace_test",
        run_id="run_test",
        user_query="周末去唱歌",
        state={"user_query": "周末去唱歌", "ranked_plans": []},
        response={"response_text": "ok", "ranked_plans": [], "selected_plan": {}},
    )

    saved = session_store.load(session_id)
    assert saved is not None
    assert saved["latest_state"]["user_query"] == "周末去唱歌"
    assert saved["turns"][-1]["user_query"] == "周末去唱歌"


def test_memory_service_observes_negative_preference() -> None:
    """临时天气约束不应直接污染长期画像。"""

    memory = MemoryService()
    memory.clear()
    memory.observe_user_query("不要室外了，今天太热")
    profile = memory.read_profile()

    assert profile["indoor_preference"] is False
    assert "室外" not in profile["disliked_keywords"]

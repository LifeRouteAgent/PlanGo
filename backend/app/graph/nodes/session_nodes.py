from __future__ import annotations

from typing import Any

from app.graph.nodes.common import append_trace, ensure_state
from app.graph.state import PlanningState, planning_state_to_legacy
from app.services.session_store import SessionStore


def session_state_saver_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    safe = planning_state_to_legacy(state)
    if state.state_meta.session_id:
        SessionStore().save_turn(
            session_id=state.state_meta.session_id,
            trace_id=state.state_meta.request_id,
            run_id=state.state_meta.state_id,
            user_query=state.context.conversation_context.last_user_message,
            state=safe,
            response=safe,
            is_revision=bool(
                state.llm_understanding and state.llm_understanding.intent.request_type == "plan_adjustment"
            ),
        )
    return {"debug": append_trace(state, "session_state_saver", "会话摘要已保存")}

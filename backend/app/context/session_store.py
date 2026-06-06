from __future__ import annotations

import json
import time
from typing import Any

from app.runtime.runtime_paths import SESSIONS_DIR, ensure_runtime_dirs
from app.runtime.runtime_store import get_runtime_store
from app.observability.trace_recorder import new_id


class SessionStore:
    """文件型会话状态存储。

    这里保存的是 demo 所需的最近一次 PlanState 和会话轮次摘要，目标是支持同一对话框里的
    “继续修改需求”，而不是让每次输入都从空状态开始。
    """

    def __init__(self) -> None:
        ensure_runtime_dirs()

    def ensure_session_id(self, session_id: str | None) -> str:
        """没有 session_id 时创建一个新的。"""

        return session_id or new_id("sess")

    def load(self, session_id: str) -> dict[str, Any] | None:
        """读取会话文件。"""

        payload = get_runtime_store().load_session(session_id)
        if isinstance(payload, dict):
            return payload
        return None

    def save_turn(
        self,
        *,
        session_id: str,
        trace_id: str,
        run_id: str,
        user_query: str,
        state: dict[str, Any],
        response: dict[str, Any],
        revision_id: str | None = None,
        is_revision: bool = False,
    ) -> None:
        """保存一次规划或修正后的最新状态。"""

        existing = self.load(session_id) or {"session_id": session_id, "turns": []}
        turns = existing.get("turns", []) if isinstance(existing.get("turns"), list) else []
        turns.append({
            "trace_id": trace_id,
            "run_id": run_id,
            "revision_id": revision_id,
            "is_revision": is_revision,
            "user_query": user_query,
            "response_text": response.get("response_text", ""),
            "selected_plan_id": (response.get("selected_plan") or {}).get("id"),
            "ranked_plan_count": len(response.get("ranked_plans", []) or []),
            "created_at": time.time(),
        })
        latest_planning_state = existing.get("latest_planning_state")
        latest_planning_response = existing.get("latest_planning_response")
        latest_planning_query = existing.get("latest_planning_query")
        if _is_planning_state(state, response):
            latest_planning_state = state
            latest_planning_response = response
            latest_planning_query = user_query

        payload = {
            "session_id": session_id,
            "updated_at": time.time(),
            "latest_trace_id": trace_id,
            "latest_run_id": run_id,
            "latest_revision_id": revision_id,
            "latest_state": state,
            "latest_response": response,
            "latest_planning_state": latest_planning_state,
            "latest_planning_response": latest_planning_response,
            "latest_planning_query": latest_planning_query,
            "turns": turns[-30:],
        }
        get_runtime_store().save_session(session_id, payload)

    def _path(self, session_id: str):
        """限制文件名只来自内部生成的短 ID。"""

        safe_name = "".join(ch for ch in session_id if ch.isalnum() or ch in {"_", "-"})
        return SESSIONS_DIR / f"{safe_name}.json"


def _is_planning_state(state: dict[str, Any], response: dict[str, Any]) -> bool:
    """判断本轮是否值得作为后续“继续规划/修正”的上下文。

    简单问答和能力问答不能覆盖最近一次规划上下文，否则用户先问“你是什么模型”，再说
    “预算改成1000”，系统就会忘记真正要修正的是上一轮行程规划。
    """

    intent_type = str(state.get("intent_type") or response.get("intent_type") or "")
    answer_mode = str(state.get("answer_mode") or response.get("answer_mode") or "")
    if intent_type in {"simple_qa", "capability"} or answer_mode in {"simple_qa", "capability"}:
        return False
    return bool(
        intent_type in {"full_trip_plan", "category_recommend", "poi_search"}
        or state.get("ranked_plans")
        or state.get("candidate_plans")
        or state.get("candidate_pois")
        or response.get("ranked_plans")
    )

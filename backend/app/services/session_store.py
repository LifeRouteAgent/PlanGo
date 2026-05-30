from __future__ import annotations

import json
import time
from typing import Any

from app.services.runtime_paths import SESSIONS_DIR, ensure_runtime_dirs
from app.services.runtime_store import get_runtime_store
from app.services.trace_recorder import new_id


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
        payload = {
            "session_id": session_id,
            "updated_at": time.time(),
            "latest_trace_id": trace_id,
            "latest_run_id": run_id,
            "latest_revision_id": revision_id,
            "latest_state": state,
            "latest_response": response,
            "turns": turns[-30:],
        }
        get_runtime_store().save_session(session_id, payload)

    def _path(self, session_id: str):
        """限制文件名只来自内部生成的短 ID。"""

        safe_name = "".join(ch for ch in session_id if ch.isalnum() or ch in {"_", "-"})
        return SESSIONS_DIR / f"{safe_name}.json"

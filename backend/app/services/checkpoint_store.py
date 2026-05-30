from __future__ import annotations

import hashlib
import json
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, TypedDict

from app.services.memory_store import ToolCacheEntry
from app.services.runtime_paths import TASKS_DIR, ensure_runtime_dirs
from app.services.trace_recorder import new_id, record_trace_event


class TaskStatus(StrEnum):
    """一次规划/执行任务的可恢复状态。"""

    CREATED = "CREATED"
    INTENT_PARSED = "INTENT_PARSED"
    CANDIDATES_RECALLED = "CANDIDATES_RECALLED"
    PLAN_GENERATED = "PLAN_GENERATED"
    PLAN_VALIDATED = "PLAN_VALIDATED"
    USER_CONFIRMED = "USER_CONFIRMED"
    EXECUTING = "EXECUTING"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"


class BookingAction(TypedDict, total=False):
    """执行阶段的单个可恢复动作。"""

    action_id: str
    type: str
    risk_level: int
    status: str
    idempotency_key: str
    request: dict[str, Any]
    result: dict[str, Any] | None
    updated_at: str


class TaskState(TypedDict, total=False):
    """任务 checkpoint 的完整状态。"""

    task_id: str
    session_id: str
    user_id: str
    status: str
    intent: dict[str, Any]
    constraints: dict[str, Any]
    candidate_summary: dict[str, Any]
    ranked_plans: list[dict[str, Any]]
    selected_plan: dict[str, Any] | None
    validation_result: dict[str, Any]
    booking_actions: list[BookingAction]
    trace_id: str
    errors: list[dict[str, Any]]
    compensations: list[dict[str, Any]]
    tool_evidence_refs: list[str]
    created_at: str
    updated_at: str


class CheckpointStore:
    """文件型 checkpoint 存储。

    每个 `task_id` 对应一个 JSON 文件。写入是覆盖式保存，事件细节仍进入 Trace。
    """

    def __init__(self) -> None:
        ensure_runtime_dirs()

    def create(
        self,
        *,
        session_id: str,
        user_id: str = "default",
        trace_id: str = "",
        task_id: str | None = None,
    ) -> TaskState:
        """创建初始任务。"""

        task: TaskState = {
            "task_id": task_id or new_id("task"),
            "session_id": session_id,
            "user_id": user_id,
            "status": TaskStatus.CREATED.value,
            "intent": {},
            "constraints": {},
            "candidate_summary": {},
            "ranked_plans": [],
            "selected_plan": None,
            "validation_result": {"issues": [], "passed": False},
            "booking_actions": [],
            "trace_id": trace_id,
            "errors": [],
            "compensations": [],
            "tool_evidence_refs": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        self.save(task)
        return task

    def save(self, task: TaskState) -> None:
        """保存 checkpoint。"""

        task["updated_at"] = _now_iso()
        self._path(str(task["task_id"])).write_text(
            json.dumps(task, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        record_trace_event(
            "checkpoint_saved",
            {
                "task_id": task.get("task_id"),
                "status": task.get("status"),
                "booking_action_count": len(task.get("booking_actions", []) or []),
            },
        )

    def load(self, task_id: str) -> TaskState | None:
        """读取 checkpoint。"""

        path = self._path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def save_from_plan_state(
        self,
        state: dict[str, Any],
        *,
        status: TaskStatus,
        task_id: str | None = None,
    ) -> TaskState:
        """从 PlanState 生成并保存 checkpoint。"""

        existing = self.load(task_id) if task_id else None
        task = existing or self.create(
            session_id=str(state.get("session_id") or ""),
            user_id=str((state.get("user_profile") or {}).get("user_id") or state.get("session_id") or "default"),
            trace_id=str(state.get("trace_id") or ""),
            task_id=task_id,
        )
        task.update({
            "status": status.value,
            "intent": {
                "intent_type": state.get("intent_type"),
                "target_categories": state.get("target_categories", []),
                "answer_mode": state.get("answer_mode"),
            },
            "constraints": state.get("constraints", {}),
            "candidate_summary": {
                key: len(value) if isinstance(value, list) else 0
                for key, value in (state.get("candidate_pois", {}) or {}).items()
            },
            "ranked_plans": state.get("ranked_plans", [])[:3],
            "selected_plan": state.get("selected_plan") or None,
            "validation_result": {
                "issues": state.get("errors", []),
                "passed": bool(state.get("verified_plans") or state.get("ranked_plans")),
            },
            "errors": state.get("errors", []),
            "trace_id": state.get("trace_id", ""),
        })
        self.save(task)
        return task

    def append_action(self, task_id: str, action: BookingAction) -> TaskState:
        """追加或更新执行动作。"""

        task = self.load(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")
        action = {**action, "updated_at": _now_iso()}
        actions = task.setdefault("booking_actions", [])
        for index, existing in enumerate(actions):
            if existing.get("action_id") == action.get("action_id"):
                actions[index] = {**existing, **action}
                break
        else:
            actions.append(action)
        task["status"] = _status_from_actions(actions)
        self.save(task)
        return task

    def resume(self, task_id: str, tool_entries: list[ToolCacheEntry] | None = None) -> dict[str, Any]:
        """生成恢复决策，不直接重跑 DAG 或交易动作。"""

        task = self.load(task_id)
        if not task:
            return {"ok": False, "decision": "not_found", "message": "没有找到任务 checkpoint。"}
        actions = task.get("booking_actions", []) or []
        has_success = any(action.get("status") == "success" for action in actions)
        unfinished = [action for action in actions if action.get("status") not in {"success", "compensated"}]
        expired = _expired_tool_entries(tool_entries or [])
        if has_success and unfinished:
            decision = "continue_or_compensate"
        elif has_success:
            decision = "already_has_success_do_not_rerun"
        elif expired:
            decision = "revalidate_tools"
        elif task.get("status") in {TaskStatus.FAILED.value, TaskStatus.PARTIALLY_EXECUTED.value}:
            decision = "resume_from_failure"
        else:
            decision = "continue"
        return {
            "ok": True,
            "decision": decision,
            "task": task,
            "unfinished_actions": unfinished,
            "expired_tool_entries": expired,
        }

    def recoverable_tasks(self) -> list[TaskState]:
        """扫描服务重启后可恢复的任务。"""

        result: list[TaskState] = []
        for path in TASKS_DIR.glob("task_*.json"):
            task = self.load(path.stem)
            if task and task.get("status") in {
                TaskStatus.EXECUTING.value,
                TaskStatus.PARTIALLY_EXECUTED.value,
                TaskStatus.FAILED.value,
            }:
                result.append(task)
        return result

    def _path(self, task_id: str) -> Path:
        safe = "".join(ch for ch in task_id if ch.isalnum() or ch in {"_", "-"})
        return TASKS_DIR / f"{safe}.json"


def make_idempotency_key(
    *,
    user_id: str,
    task_id: str,
    action_type: str,
    target_id: str,
    slot_time: str = "",
    amount: int | float | str = "",
) -> str:
    """生成交易动作幂等键。"""

    raw = json.dumps(
        {
            "user_id": user_id,
            "task_id": task_id,
            "action_type": action_type,
            "target_id": target_id,
            "slot_time": slot_time,
            "amount": amount,
        },
        sort_keys=True,
        default=str,
    )
    return "idem_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _status_from_actions(actions: list[BookingAction]) -> str:
    if not actions:
        return TaskStatus.USER_CONFIRMED.value
    statuses = {action.get("status") for action in actions}
    if statuses <= {"success"}:
        return TaskStatus.COMPLETED.value
    if "success" in statuses and any(status in statuses for status in {"failed", "running", "pending"}):
        return TaskStatus.PARTIALLY_EXECUTED.value
    if "failed" in statuses:
        return TaskStatus.FAILED.value
    return TaskStatus.EXECUTING.value


def _expired_tool_entries(entries: list[ToolCacheEntry]) -> list[ToolCacheEntry]:
    now = time.time()
    result: list[ToolCacheEntry] = []
    for entry in entries:
        expires_at = str(entry.get("expires_at") or "")
        try:
            ts = time.mktime(time.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            continue
        if ts < now:
            result.append(entry)
    return result


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

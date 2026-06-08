from __future__ import annotations

import hashlib
import json
import time
from enum import StrEnum
from typing import Any, TypedDict

from app.memory.memory_store import ToolCacheEntry
from app.runtime.runtime_store import get_runtime_store
from app.observability.trace_recorder import new_id, record_trace_event


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

    version: int
    updated_by_run_id: str
    state_revision: int
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
        pass

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
            "version": 1,
            "updated_by_run_id": "",
            "state_revision": 0,
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

        previous = self.load(str(task["task_id"]))
        if previous:
            task["version"] = int(previous.get("version", 1) or 1) + 1
            task.setdefault(
                "state_revision",
                int(previous.get("state_revision", 0) or 0),
            )
        else:
            task.setdefault("version", 1)
            task.setdefault("state_revision", 0)
        task.setdefault("updated_by_run_id", "")
        task["updated_at"] = _now_iso()
        get_runtime_store().save_task(str(task["task_id"]), task)
        record_trace_event(
            "checkpoint_saved",
            {
                "task_id": task.get("task_id"),
                "status": task.get("status"),
                "version": task.get("version"),
                "state_revision": task.get("state_revision"),
                "updated_by_run_id": task.get("updated_by_run_id"),
                "booking_action_count": len(task.get("booking_actions", []) or []),
            },
        )

    def load(self, task_id: str) -> TaskState | None:
        """读取 checkpoint。"""

        data = get_runtime_store().load_task(task_id)
        return data if isinstance(data, dict) else None

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
            user_id=str(
                (state.get("user_profile") or {}).get("user_id")
                or state.get("session_id")
                or "default"
            ),
            trace_id=str(state.get("trace_id") or ""),
            task_id=task_id,
        )
        previous_revision = int(task.get("state_revision", 0) or 0)
        task.update({
            "updated_by_run_id": str(state.get("run_id") or task.get("updated_by_run_id") or ""),
            "state_revision": previous_revision + 1,
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

    def resume(
        self, task_id: str, tool_entries: list[ToolCacheEntry] | None = None
    ) -> dict[str, Any]:
        """生成恢复决策，不直接重跑 DAG 或交易动作。"""

        task = self.load(task_id)
        if not task:
            return {"ok": False, "decision": "not_found", "message": "没有找到任务 checkpoint。"}
        actions = task.get("booking_actions", []) or []
        has_success = any(action.get("status") == "success" for action in actions)
        unfinished = [
            action for action in actions if action.get("status") not in {"success", "compensated"}
        ]
        expired = _expired_tool_entries(tool_entries or [])
        failed_unfinished = [action for action in unfinished if action.get("status") == "failed"]
        if has_success and failed_unfinished:
            decision = "compensate"
        elif has_success and unfinished:
            decision = "continue_unfinished_actions"
        elif has_success:
            decision = "require_user_confirmation"
        elif expired:
            decision = "revalidate_tools"
        elif task.get("status") in {TaskStatus.FAILED.value, TaskStatus.PARTIALLY_EXECUTED.value}:
            decision = (
                "compensate"
                if task.get("status") == TaskStatus.PARTIALLY_EXECUTED.value
                else "require_user_confirmation"
            )
        else:
            decision = "continue"
        return {
            "ok": True,
            "decision": decision,
            "message": _resume_message(decision),
            "task": task,
            "unfinished_actions": unfinished,
            "expired_tool_entries": expired,
        }

    def recoverable_tasks(self) -> list[TaskState]:
        """扫描服务重启后可恢复的任务。"""

        result: list[TaskState] = []
        for task in get_runtime_store().list_tasks():
            if task and task.get("status") in {
                TaskStatus.EXECUTING.value,
                TaskStatus.PARTIALLY_EXECUTED.value,
                TaskStatus.FAILED.value,
            }:
                result.append(task)
        return result


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
    if "success" in statuses and any(
        status in statuses for status in {"failed", "running", "pending"}
    ):
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


def _resume_message(decision: str) -> str:
    """把恢复决策转成人可读说明，前端和观测面板可直接展示。"""

    messages = {
        "continue": "任务可以从最近 checkpoint 继续。",
        "revalidate_tools": "部分工具证据已过期，需要先重新校验路线、库存或天气。",
        "continue_unfinished_actions": "已有成功动作，禁止重跑成功订单，只继续未完成动作。",
        "compensate": "任务处于部分成功或失败状态，需要先补偿或处理失败项。",
        "require_user_confirmation": "已有交易结果或失败边界，继续前需要用户重新确认。",
        "not_found": "没有找到任务 checkpoint。",
    }
    return messages.get(decision, "需要人工检查恢复策略。")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

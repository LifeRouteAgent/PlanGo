from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from enum import StrEnum
from typing import Any

from app.memory.memory_store import ToolCacheEntry
from app.runtime.runtime_store import get_runtime_store
from app.observability.trace_recorder import new_id, TraceRecorder


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


@dataclass
class BookingAction:
    """执行阶段的单个可恢复动作。"""

    action_id: str = ""
    type: str = ""
    risk_level: int = 0
    status: str = ""
    idempotency_key: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    updated_at: str = ""


@dataclass
class TaskState:
    """任务 checkpoint 的完整状态。"""

    version: int = 1
    updated_by_run_id: str = ""
    state_revision: int = 0
    task_id: str = ""
    session_id: str = ""
    user_id: str = "default"
    status: str = TaskStatus.CREATED.value
    intent: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    candidate_summary: dict[str, Any] = field(default_factory=dict)
    ranked_plans: list[dict[str, Any]] = field(default_factory=list)
    selected_plan: dict[str, Any] | None = None
    validation_result: dict[str, Any] = field(
        default_factory=lambda: {"issues": [], "passed": False}
    )
    booking_actions: list[BookingAction] = field(default_factory=list)
    trace_id: str = ""
    errors: list[dict[str, Any]] = field(default_factory=list)
    compensations: list[dict[str, Any]] = field(default_factory=list)
    tool_evidence_refs: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        """从 runtime_store 返回的 dict 重建 TaskState。"""
        kwargs = {k: v for k, v in data.items() if v is not None}
        booking_raw = kwargs.pop("booking_actions", []) or []
        kwargs["booking_actions"] = [
            BookingAction(**a) if isinstance(a, dict) else a for a in booking_raw
        ]
        return cls(**kwargs)


class CheckpointStore:
    """文件型 checkpoint 存储。

    每个 `task_id` 对应一个 JSON 文件。写入是覆盖式保存，事件细节仍进入 Trace。
    """

    @staticmethod
    def create(
        *,
        session_id: str,
        user_id: str = "default",
        trace_id: str = "",
        task_id: str | None = None,
    ) -> TaskState:
        """创建初始任务。"""
        at_time = _now_iso()
        task = TaskState(
            task_id=task_id or new_id("task"),
            session_id=session_id,
            user_id=user_id,
            trace_id=trace_id,
            created_at=at_time,
            updated_at=at_time,
        )
        CheckpointStore.save(task)
        return task

    @staticmethod
    def save(task: TaskState) -> None:
        """保存 checkpoint。"""

        previous = CheckpointStore.load(task.task_id)
        if previous:
            task.version = previous.version + 1
            if task.state_revision == 0:
                task.state_revision = previous.state_revision
        task.updated_at = _now_iso()
        get_runtime_store().save_task(task.task_id, asdict(task))
        TraceRecorder.record(
            "checkpoint_saved",
            {
                "task_id": task.task_id,
                "status": task.status,
                "version": task.version,
                "state_revision": task.state_revision,
                "updated_by_run_id": task.updated_by_run_id,
                "booking_action_count": len(task.booking_actions),
            },
        )

    @staticmethod
    def load(task_id: str) -> TaskState | None:
        """读取 checkpoint。"""

        data = get_runtime_store().load_task(task_id)
        return TaskState.from_dict(data) if isinstance(data, dict) else None

    @staticmethod
    def save_from_plan_state(
        state: dict[str, Any],
        *,
        status: TaskStatus,
        task_id: str | None = None,
    ) -> TaskState:
        """从 PlanState 生成并保存 checkpoint。"""

        existing = CheckpointStore.load(task_id) if task_id else None
        task = existing or CheckpointStore.create(
            session_id=str(state.get("session_id") or ""),
            user_id=str(
                (state.get("user_profile") or {}).get("user_id")
                or state.get("session_id")
                or "default"
            ),
            trace_id=str(state.get("trace_id") or ""),
            task_id=task_id,
        )
        previous_revision = task.state_revision
        task.updated_by_run_id = str(state.get("run_id") or task.updated_by_run_id or "")
        task.state_revision = previous_revision + 1
        task.status = status.value
        task.intent = {
            "intent_type": state.get("intent_type"),
            "target_categories": state.get("target_categories", []),
            "answer_mode": state.get("answer_mode"),
        }
        task.constraints = state.get("constraints", {})
        task.candidate_summary = {
            key: len(value) if isinstance(value, list) else 0
            for key, value in (state.get("candidate_pois", {}) or {}).items()
        }
        task.ranked_plans = (state.get("ranked_plans") or [])[:3]
        task.selected_plan = state.get("selected_plan") or None
        task.validation_result = {
            "issues": state.get("errors", []),
            "passed": bool(state.get("verified_plans") or state.get("ranked_plans")),
        }
        task.errors = state.get("errors", [])
        task.trace_id = str(state.get("trace_id") or "")
        CheckpointStore.save(task)
        return task

    @staticmethod
    def append_action(task_id: str, action: BookingAction) -> TaskState:
        """追加或更新执行动作。"""

        task = CheckpointStore.load(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")
        action.updated_at = _now_iso()
        for index, existing in enumerate(task.booking_actions):
            if existing.action_id == action.action_id:
                task.booking_actions[index] = BookingAction(
                    **{**asdict(existing), **asdict(action)},
                )
                break
        else:
            task.booking_actions.append(action)
        task.status = _status_from_actions(task.booking_actions)
        CheckpointStore.save(task)
        return task

    @staticmethod
    def resume(task_id: str, tool_entries: list[ToolCacheEntry] | None = None) -> dict[str, Any]:
        """生成恢复决策，不直接重跑 DAG 或交易动作。"""

        task = CheckpointStore.load(task_id)
        if not task:
            return {"ok": False, "decision": "not_found", "message": "没有找到任务 checkpoint。"}
        actions = task.booking_actions
        has_success = any(a.status == "success" for a in actions)
        unfinished = [a for a in actions if a.status not in {"success", "compensated"}]
        expired = _expired_tool_entries(tool_entries or [])
        failed_unfinished = [a for a in unfinished if a.status == "failed"]
        if has_success and failed_unfinished:
            decision = "compensate"
        elif has_success and unfinished:
            decision = "continue_unfinished_actions"
        elif has_success:
            decision = "require_user_confirmation"
        elif expired:
            decision = "revalidate_tools"
        elif task.status in {TaskStatus.FAILED.value, TaskStatus.PARTIALLY_EXECUTED.value}:
            decision = (
                "compensate"
                if task.status == TaskStatus.PARTIALLY_EXECUTED.value
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

    @staticmethod
    def recoverable_tasks() -> list[TaskState]:
        """扫描服务重启后可恢复的任务。"""

        result: list[TaskState] = []
        for raw in get_runtime_store().list_tasks():
            if raw and isinstance(raw, dict):
                task = TaskState.from_dict(raw)
                if task.status in {
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
    statuses = {a.status for a in actions}
    if statuses <= {"success"}:
        return TaskStatus.COMPLETED.value
    if "success" in statuses and any(s in statuses for s in {"failed", "running", "pending"}):
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

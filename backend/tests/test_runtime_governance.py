from __future__ import annotations

from app.runtime.checkpoint_store import CheckpointStore, TaskStatus, make_idempotency_key
from app.evaluation.eval_runner import EvalCase, EvalRunner
from app.memory.memory_store import FileMemoryStore, make_cache_key
from app.tools.tool_policy import RiskLevel, ToolPolicy


def test_memory_store_session_and_tool_cache_ttl() -> None:
    """MemoryStore 分层保存会话事件和工具缓存，过期缓存不能用于新执行。"""

    store = FileMemoryStore()
    session_id = "test_session_memory_store"
    store.append_session_event(
        session_id,
        {"type": "plan_selected", "plan_id": "p1", "plan_summary": "KTV + 晚餐"},
    )
    session = store.load_session(session_id)
    assert session["selected_plan_id"] == "p1"
    assert session["last_selected_plan_summary"] == "KTV + 晚餐"

    cache_key = make_cache_key("amap.route", {"from": "a", "to": "b"})
    store.put_tool_cache({
        "cache_key": cache_key,
        "tool_name": "amap.route",
        "request_hash": "hash",
        "result_summary": {"duration_minutes": 20},
        "full_result_path": "",
        "source": "amap",
        "fetched_at": "2026-05-31T00:00:00Z",
        "expires_at": "2999-01-01T00:00:00Z",
        "confidence": 0.9,
        "fallback_used": False,
    })
    assert store.get_tool_cache(cache_key)["result_summary"]["duration_minutes"] == 20

    expired_key = make_cache_key("ticket.stock", {"poi": "x"})
    store.put_tool_cache({
        "cache_key": expired_key,
        "tool_name": "ticket.stock",
        "request_hash": "hash",
        "result_summary": {"available": True},
        "full_result_path": "",
        "source": "mock",
        "fetched_at": "2026-05-31T00:00:00Z",
        "expires_at": "2000-01-01T00:00:00Z",
        "confidence": 0.5,
        "fallback_used": False,
    })
    assert store.get_tool_cache(expired_key) is None


def test_checkpoint_resume_blocks_blind_rerun_after_success() -> None:
    """已有成功交易时，恢复策略不能盲目重跑整单。"""

    store = CheckpointStore()
    task = store.create(
        session_id="session_checkpoint_test",
        user_id="user_checkpoint_test",
        trace_id="trace_checkpoint_test",
        task_id="task_checkpoint_test",
    )
    key = make_idempotency_key(
        user_id="user_checkpoint_test",
        task_id=task["task_id"],
        action_type="ticket_order",
        target_id="poi_1",
    )
    store.append_action(
        task["task_id"],
        {
            "action_id": "ticket_1",
            "type": "ticket_order",
            "risk_level": 3,
            "status": "success",
            "idempotency_key": key,
            "request": {"poi_id": "poi_1"},
            "result": {"order_id": "mock_order"},
        },
    )

    decision = store.resume(task["task_id"])

    assert decision["ok"] is True
    assert decision["decision"] == "require_user_confirmation"


def test_tool_policy_requires_confirmation_and_verified_target() -> None:
    """Level 3 工具必须确认、必须幂等，并且目标来自已验证候选。"""

    policy = ToolPolicy()
    request = {
        "tool_name": "mock.reserve",
        "risk_level": int(RiskLevel.TRANSACTION),
        "user_id": "u1",
        "session_id": "s1",
        "task_id": "t1",
        "idempotency_key": "idem_1",
        "params": {
            "target_id": "poi_1",
            "validated_item_ids": ["poi_2"],
            "confirmed": True,
            "confirmed_source": "unit_test",
            "people_count": 2,
            "budget": 300,
        },
        "requires_confirmation": True,
        "confirmed_source": "unit_test",
    }

    issues = policy.validate(request)

    assert any(issue["code"] == "target_not_verified" for issue in issues)
    request["params"]["validated_item_ids"] = ["poi_1"]
    assert policy.validate(request) == []


def test_eval_runner_scores_five_layers() -> None:
    """EvalRunner 支持意图、规划、工具、安全和业务五层评测。"""

    runner = EvalRunner()
    cases = [
        EvalCase(
            "intent_1",
            "intent",
            "两个人唱歌",
            expected={"intent_type": "full_trip_plan", "people_count": 2},
        ),
        EvalCase(
            "plan_1",
            "planning_quality",
            "安排一下",
            expected={"min_plan_count": 1, "requires_route": True},
        ),
        EvalCase(
            "tool_1",
            "tool_calling",
            "预订",
            expected={"required_events": ["tool_started"], "no_duplicate_tool_calls": True},
        ),
        EvalCase("safe_1", "fulfillment_safety", "购票", expected={}),
        EvalCase("biz_1", "business_effect", "分享", expected={"share_rate": 0.1}),
    ]
    outcomes = {
        "intent_1": {"intent_type": "full_trip_plan", "people_count": 2},
        "plan_1": {
            "ranked_plans": [
                {"id": "p1", "route_segments": [{"duration_minutes": 10}], "items": [{"id": "a"}]}
            ]
        },
        "tool_1": {
            "trace_events": [{"event": "tool_started", "tool_name": "route", "request_hash": "1"}]
        },
        "safe_1": {
            "booking_actions": [{
                "action_id": "a",
                "risk_level": 3,
                "idempotency_key": "idem",
                "status": "success",
                "confirmed": True,
            }]
        },
        "biz_1": {"business_metrics": {"share_rate": 0.2}},
    }

    summary = runner.run(cases, outcomes)

    assert summary["passed"] == 5
    assert summary["layers"]["intent"]["passed"] == 1


def test_eval_runner_splits_harness_context_memory_and_recovery_layers() -> None:
    """新评测拆分运行合同、上下文治理、记忆收益和恢复正确性，避免混成一个总分。"""

    runner = EvalRunner()
    cases = [
        EvalCase(
            "harness_contract",
            "harness_regression",
            "合同稳定性",
            expected={
                "required_fields": ["response_text", "ranked_plans"],
                "requires_trace_id": True,
                "requires_task_id": True,
                "max_error_count": 0,
            },
        ),
        EvalCase(
            "context_clip",
            "context_governance",
            "上下文裁剪",
            expected={
                "must_keep_hard_constraints": ["people_count", "budget"],
                "max_tool_evidence": 3,
                "top_k_per_category": 8,
                "forbidden_prompt_fields": ["candidate_pois.poi_entertainment[8:12]"],
            },
        ),
        EvalCase(
            "memory_gain",
            "memory_benefit",
            "和上次差不多",
            path="ablation_experiment",
            expected={
                "requires_memory_context": True,
                "min_score_delta": 0.1,
                "expected_memory_tags": ["KTV"],
            },
        ),
        EvalCase(
            "resume_boundary",
            "recovery_correctness",
            "恢复任务",
            expected={
                "resume_decision": "require_user_confirmation",
                "must_not_rerun_successful_action": True,
                "requires_idempotency_keys": True,
            },
        ),
    ]
    outcomes = {
        "harness_contract": {
            "response_text": "ok",
            "ranked_plans": [],
            "trace_id": "trace_1",
            "task_id": "task_1",
            "errors": [],
        },
        "context_clip": {
            "context_snapshot": {
                "user_constraints": {"hard_constraints": {"people_count": 2, "budget": 500}},
                "tool_evidence": [{"evidence_ref": "a"}],
                "prompt_meta": {
                    "top_k_per_category": 8,
                    "clipped_fields": ["candidate_pois.poi_entertainment[8:12]"],
                },
            }
        },
        "memory_gain": {
            "memory_context_used": True,
            "score_delta": 0.15,
            "memory_fit_tags": ["KTV", "室内"],
        },
        "resume_boundary": {
            "resume_decision": "require_user_confirmation",
            "reran_successful_action": False,
            "booking_actions": [{
                "action_id": "ticket_1",
                "risk_level": 3,
                "idempotency_key": "idem_1",
            }],
        },
    }

    summary = runner.run(cases, outcomes)

    assert summary["passed"] == 4
    assert summary["layers"]["context_governance"]["passed"] == 1
    assert summary["paths"]["fixed_benchmark"]["passed"] == 3
    assert summary["paths"]["ablation_experiment"]["passed"] == 1


def test_eval_runner_ablation_and_runtime_artifact_paths() -> None:
    """对照实验和运行工件聚合是两条独立评测路径。"""

    runner = EvalRunner()
    cases = [
        EvalCase(
            "memory_gain",
            "memory_benefit",
            "历史偏好增益",
            path="ablation_experiment",
            expected={"requires_memory_context": True, "min_score_delta": 0.1},
        )
    ]
    baseline = {"memory_gain": {"memory_context_used": False, "score_delta": 0.0}}
    treatment = {"memory_gain": {"memory_context_used": True, "score_delta": 0.2}}

    experiment = runner.run_ablation_experiment(cases, baseline, treatment)
    artifacts = runner.aggregate_runtime_artifacts([
        {
            "contract_passed": True,
            "cache_hit_rate": 0.5,
            "recovered_successfully": True,
            "partial_success": False,
            "compensated": False,
            "user_accepted": True,
            "tool_call_count": 4,
            "trace_event_count": 20,
            "rejection_reason": "",
            "failure_code": "",
        },
        {
            "contract_passed": False,
            "cache_hit_rate": 0.0,
            "recovered_successfully": False,
            "partial_success": True,
            "compensated": True,
            "user_accepted": False,
            "tool_call_count": 6,
            "trace_event_count": 30,
            "rejection_reason": "too_far",
            "failure_code": "slot_unavailable",
        },
    ])

    assert experiment["wins"] == 1
    assert experiment["avg_delta"] > 0
    assert artifacts["metrics"]["contract_pass_rate"] == 0.5
    assert artifacts["metrics"]["avg_tool_calls"] == 5.0
    assert artifacts["top_failure_codes"][0]["value"] == "slot_unavailable"

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class EvalCase:
    """本地生活 Agent 的结构化评测用例。

    评测不只看回答是否自然，而是把一次规划拆成意图、方案、工具、安全和业务效果五层。
    `expected` 只写关键字段，避免因为文案微调导致评测大面积误报。
    """

    case_id: str
    layer: str
    user_query: str
    path: str = "fixed_benchmark"
    user_profile: dict[str, Any] = field(default_factory=dict)
    expected: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """单条评测结果。"""

    case_id: str
    layer: str
    passed: bool
    score: float
    path: str = "fixed_benchmark"
    failures: list[str] = field(default_factory=list)


class EvalRunner:
    """五层评测执行器。

    这里不直接绑定 LangGraph，调用方可以把真实 PlanState、trace 或 mock outcome 传进来。
    这样 CI 可以跑轻量单测，演示前也可以接真实链路做回归。
    """

    def __init__(
        self, graders: dict[str, Callable[[EvalCase, dict[str, Any]], EvalResult]] | None = None
    ) -> None:
        self.graders = graders or default_graders()

    def run_case(self, case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
        """运行单条评测。"""

        grader = self.graders.get(case.layer)
        if not grader:
            return EvalResult(
                case_id=case.case_id,
                layer=case.layer,
                passed=False,
                score=0.0,
                failures=[f"missing grader for layer: {case.layer}"],
            )
        return grader(case, outcome)

    def run(self, cases: list[EvalCase], outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """批量运行评测并按层聚合通过率。"""

        results = [self.run_case(case, outcomes.get(case.case_id, {})) for case in cases]
        by_layer: dict[str, list[EvalResult]] = {}
        by_path: dict[str, list[EvalResult]] = {}
        for result in results:
            by_layer.setdefault(result.layer, []).append(result)
            by_path.setdefault(result.path, []).append(result)
        return {
            "total": len(results),
            "passed": sum(1 for result in results if result.passed),
            "layers": {
                layer: {
                    "total": len(items),
                    "passed": sum(1 for item in items if item.passed),
                    "avg_score": round(sum(item.score for item in items) / max(1, len(items)), 4),
                }
                for layer, items in by_layer.items()
            },
            "paths": {
                path: {
                    "total": len(items),
                    "passed": sum(1 for item in items if item.passed),
                    "avg_score": round(sum(item.score for item in items) / max(1, len(items)), 4),
                }
                for path, items in by_path.items()
            },
            "results": [result.__dict__ for result in results],
        }

    def run_fixed_benchmark(
        self,
        cases: list[EvalCase],
        outcomes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """运行固定 benchmark，只验证合同和回归，不和线上指标混在一起。"""

        fixed_cases = [case for case in cases if case.path == "fixed_benchmark"]
        return self.run(fixed_cases, outcomes)

    def run_ablation_experiment(
        self,
        cases: list[EvalCase],
        baseline_outcomes: dict[str, dict[str, Any]],
        treatment_outcomes: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """运行对照实验，量化上下文治理、Memory 或恢复模块的增益。"""

        experiment_cases = [case for case in cases if case.path == "ablation_experiment"]
        comparisons: list[dict[str, Any]] = []
        for case in experiment_cases:
            baseline = self.run_case(case, baseline_outcomes.get(case.case_id, {}))
            treatment = self.run_case(case, treatment_outcomes.get(case.case_id, {}))
            comparisons.append({
                "case_id": case.case_id,
                "layer": case.layer,
                "baseline_score": baseline.score,
                "treatment_score": treatment.score,
                "delta": round(treatment.score - baseline.score, 4),
                "passed_changed": treatment.passed != baseline.passed,
                "baseline_failures": baseline.failures,
                "treatment_failures": treatment.failures,
            })
        return {
            "path": "ablation_experiment",
            "total": len(comparisons),
            "wins": sum(1 for item in comparisons if item["delta"] > 0),
            "losses": sum(1 for item in comparisons if item["delta"] < 0),
            "avg_delta": round(
                sum(float(item["delta"]) for item in comparisons) / max(1, len(comparisons)),
                4,
            ),
            "comparisons": comparisons,
        }

    def aggregate_runtime_artifacts(self, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        """聚合运行工件，不把它当作模型能力分数。

        输入来自 trace、checkpoint、session 和业务事件，输出用于观测运行质量：
        合同稳定性、缓存命中、恢复边界、用户采纳和补偿情况。
        """

        if not artifacts:
            return {
                "path": "runtime_artifact_aggregation",
                "total_runs": 0,
                "metrics": {},
            }
        return {
            "path": "runtime_artifact_aggregation",
            "total_runs": len(artifacts),
            "metrics": {
                "contract_pass_rate": _rate(artifacts, "contract_passed"),
                "cache_hit_rate": _avg_metric(artifacts, "cache_hit_rate"),
                "checkpoint_recovery_rate": _rate(artifacts, "recovered_successfully"),
                "partial_success_rate": _rate(artifacts, "partial_success"),
                "compensation_rate": _rate(artifacts, "compensated"),
                "user_acceptance_rate": _rate(artifacts, "user_accepted"),
                "avg_tool_calls": _avg_metric(artifacts, "tool_call_count"),
                "avg_trace_events": _avg_metric(artifacts, "trace_event_count"),
            },
            "top_rejection_reasons": _top_counts(artifacts, "rejection_reason", limit=5),
            "top_failure_codes": _top_counts(artifacts, "failure_code", limit=5),
        }


def default_graders() -> dict[str, Callable[[EvalCase, dict[str, Any]], EvalResult]]:
    """默认五层评分器。"""

    return {
        "intent": grade_intent,
        "planning_quality": grade_planning_quality,
        "tool_calling": grade_tool_calling,
        "fulfillment_safety": grade_fulfillment_safety,
        "business_effect": grade_business_effect,
        "harness_regression": grade_harness_regression,
        "context_governance": grade_context_governance,
        "memory_benefit": grade_memory_benefit,
        "recovery_correctness": grade_recovery_correctness,
    }


def grade_harness_regression(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """Harness regression：验证运行时合同稳定性，而不是评价模型聪不聪明。"""

    failures: list[str] = []
    for field_name in case.expected.get("required_fields", []):
        if field_name not in outcome:
            failures.append(f"missing_required_field:{field_name}")
    expected_status = case.expected.get("execution_status")
    if expected_status and outcome.get("execution_status") != expected_status:
        failures.append(
            f"execution_status:expected={expected_status}:actual={outcome.get('execution_status')}"
        )
    if case.expected.get("requires_trace_id") and not outcome.get("trace_id"):
        failures.append("missing_trace_id")
    if case.expected.get("requires_task_id") and not outcome.get("task_id"):
        failures.append("missing_task_id")
    if case.expected.get("max_error_count") is not None:
        max_errors = int(case.expected["max_error_count"])
        if len(outcome.get("errors", []) or []) > max_errors:
            failures.append("too_many_errors")
    return _score_result(case, "harness_regression", failures)


def grade_context_governance(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """上下文治理：验证硬约束保留、候选裁剪、完整历史和完整工具结果不进 prompt。"""

    snapshot = outcome.get("context_snapshot", {})
    prompt_meta = snapshot.get("prompt_meta", {}) if isinstance(snapshot, dict) else {}
    user_constraints = snapshot.get("user_constraints", {}) if isinstance(snapshot, dict) else {}
    failures: list[str] = []
    for field_name in case.expected.get("must_keep_hard_constraints", []):
        if field_name not in user_constraints.get("hard_constraints", {}):
            failures.append(f"hard_constraint_clipped:{field_name}")
    max_evidence = int(case.expected.get("max_tool_evidence", 999))
    if len(snapshot.get("tool_evidence", []) if isinstance(snapshot, dict) else []) > max_evidence:
        failures.append("too_much_tool_evidence")
    max_top_k = int(case.expected.get("top_k_per_category", 999))
    if int(prompt_meta.get("top_k_per_category", 0) or 0) > max_top_k:
        failures.append("top_k_exceeded")
    forbidden_fields = set(case.expected.get("forbidden_prompt_fields", []))
    clipped_fields = set(prompt_meta.get("clipped_fields", []) or [])
    if forbidden_fields and not forbidden_fields.intersection(clipped_fields):
        failures.append("forbidden_fields_not_reported_as_clipped")
    return _score_result(case, "context_governance", failures)


def grade_memory_benefit(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """Memory benefit：通过对照实验验证记忆是否带来召回、排序或解释增益。"""

    failures: list[str] = []
    if case.expected.get("requires_memory_context") and not outcome.get("memory_context_used"):
        failures.append("memory_context_not_used")
    min_delta = float(case.expected.get("min_score_delta", 0) or 0)
    actual_delta = float(outcome.get("score_delta", 0) or 0)
    if actual_delta < min_delta:
        failures.append(f"memory_delta_too_low:{actual_delta}")
    expected_tags = set(case.expected.get("expected_memory_tags", []))
    actual_tags = set(outcome.get("memory_fit_tags", []) or [])
    missing_tags = expected_tags - actual_tags
    for tag in sorted(missing_tags):
        failures.append(f"missing_memory_tag:{tag}")
    return _score_result(case, "memory_benefit", failures)


def grade_recovery_correctness(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """恢复正确性：验证刷新、重启、部分成功和成功订单不重跑边界。"""

    failures: list[str] = []
    expected_decision = case.expected.get("resume_decision")
    if expected_decision and outcome.get("resume_decision") != expected_decision:
        failures.append(
            f"resume_decision:expected={expected_decision}:actual={outcome.get('resume_decision')}"
        )
    if case.expected.get("must_not_rerun_successful_action") and outcome.get(
        "reran_successful_action"
    ):
        failures.append("reran_successful_action")
    if case.expected.get("requires_idempotency_keys"):
        for action in outcome.get("booking_actions", []) or []:
            if int(action.get("risk_level", 0) or 0) >= 3 and not action.get("idempotency_key"):
                failures.append(f"missing_idempotency:{action.get('action_id')}")
    if case.expected.get("expired_tool_requires_revalidation") and not outcome.get(
        "revalidated_expired_tools"
    ):
        failures.append("expired_tool_not_revalidated")
    return _score_result(case, "recovery_correctness", failures)


def grade_intent(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """意图解析评测：场景、人数、时间、预算、must_pois 等字段是否正确。"""

    return _field_match_result(
        case, outcome, ["intent_type", "people_count", "budget", "must_pois", "activity_intents"]
    )


def grade_planning_quality(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """规划质量评测：硬约束、路线连续性、组合差异度和总时长。"""

    failures: list[str] = []
    plans = outcome.get("ranked_plans", [])
    if case.expected.get("min_plan_count") and len(plans) < int(case.expected["min_plan_count"]):
        failures.append("plan_count_too_low")
    if case.expected.get("requires_route") and not any(
        plan.get("route_segments") for plan in plans
    ):
        failures.append("missing_route_segments")
    if case.expected.get("max_duration_minutes"):
        max_duration = int(case.expected["max_duration_minutes"])
        if any(int(plan.get("total_duration_minutes", 0) or 0) > max_duration for plan in plans):
            failures.append("duration_exceeded")
    if case.expected.get("distinct_poi_combinations") and _duplicate_plan_items(plans):
        failures.append("duplicate_poi_combinations")
    return _score_result(case, "planning_quality", failures)


def grade_tool_calling(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """工具调用评测：缓存、路线、库存和交易前置查询是否按顺序发生。"""

    events = outcome.get("trace_events", [])
    failures: list[str] = []
    required_events = case.expected.get("required_events", [])
    seen = [
        str(event.get("event") or event.get("type") or "")
        for event in events
        if isinstance(event, dict)
    ]
    for event_name in required_events:
        if event_name not in seen:
            failures.append(f"missing_event:{event_name}")
    if case.expected.get("no_duplicate_tool_calls") and _has_duplicate_tool_calls(events):
        failures.append("duplicate_tool_calls")
    return _score_result(case, "tool_calling", failures)


def grade_fulfillment_safety(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """履约安全评测：高风险工具确认、幂等键、支付阻断和补偿。"""

    actions = outcome.get("booking_actions", [])
    failures: list[str] = []
    for action in actions:
        risk = int(action.get("risk_level", 0) or 0)
        if risk >= 3 and not action.get("idempotency_key"):
            failures.append(f"missing_idempotency:{action.get('action_id')}")
        if risk >= 3 and action.get("status") == "running" and not action.get("confirmed"):
            failures.append(f"missing_confirmation:{action.get('action_id')}")
        if risk >= 4 and action.get("status") == "success":
            failures.append(f"payment_auto_executed:{action.get('action_id')}")
    if (
        case.expected.get("payment_required_should_stop")
        and outcome.get("execution_status") == "completed"
    ):
        failures.append("payment_required_not_stopped")
    return _score_result(case, "fulfillment_safety", failures)


def grade_business_effect(case: EvalCase, outcome: dict[str, Any]) -> EvalResult:
    """业务效果评测：保存、分享、导航、预订转化和拒绝原因统计是否被记录。"""

    metrics = outcome.get("business_metrics", {})
    failures: list[str] = []
    for key, min_value in case.expected.items():
        if float(metrics.get(key, 0) or 0) < float(min_value):
            failures.append(f"metric_below_expectation:{key}")
    return _score_result(case, "business_effect", failures)


def _field_match_result(case: EvalCase, outcome: dict[str, Any], keys: list[str]) -> EvalResult:
    failures: list[str] = []
    for key in keys:
        if key not in case.expected:
            continue
        actual = outcome.get(key)
        expected = case.expected[key]
        if isinstance(expected, list):
            actual_values = actual if isinstance(actual, list) else []
            for value in expected:
                if value not in actual_values and not _list_contains_mapping(actual_values, value):
                    failures.append(f"{key}:missing:{value}")
        elif actual != expected:
            failures.append(f"{key}:expected={expected}:actual={actual}")
    return _score_result(case, "intent", failures)


def _score_result(case: EvalCase, layer: str, failures: list[str]) -> EvalResult:
    score = max(0.0, 1.0 - len(failures) * 0.25)
    return EvalResult(
        case_id=case.case_id,
        layer=layer,
        passed=not failures,
        score=score,
        path=case.path,
        failures=failures,
    )


def _list_contains_mapping(items: list[Any], expected: Any) -> bool:
    if not isinstance(expected, dict):
        return False
    for item in items:
        if not isinstance(item, dict):
            continue
        if all(item.get(key) == value for key, value in expected.items()):
            return True
    return False


def _duplicate_plan_items(plans: list[dict[str, Any]]) -> bool:
    signatures: set[tuple[str, ...]] = set()
    for plan in plans:
        signature = tuple(
            str(item.get("id")) for item in plan.get("items", []) if isinstance(item, dict)
        )
        if signature in signatures:
            return True
        signatures.add(signature)
    return False


def _has_duplicate_tool_calls(events: list[dict[str, Any]]) -> bool:
    seen: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        tool_name = str(event.get("tool_name") or "")
        request_hash = str(event.get("request_hash") or event.get("cache_key") or "")
        if not tool_name or not request_hash:
            continue
        key = (tool_name, request_hash)
        if key in seen:
            return True
        seen.add(key)
    return False


def _rate(items: list[dict[str, Any]], key: str) -> float:
    return round(
        sum(1 for item in items if bool(item.get(key))) / max(1, len(items)),
        4,
    )


def _avg_metric(items: list[dict[str, Any]], key: str) -> float:
    values = [float(item.get(key, 0) or 0) for item in items]
    return round(sum(values) / max(1, len(values)), 4)


def _top_counts(items: list[dict[str, Any]], key: str, *, limit: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:limit]
    ]

from __future__ import annotations

from typing import Any

Issue = dict[str, Any]


ISSUE_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "candidate_empty": (
        "error",
        "没有找到可用于规划的候选地点。",
        "放宽类别、扩大搜索范围，或换一个更明确的偏好。",
    ),
    "restaurant_unavailable": (
        "error",
        "餐厅当前不可用或没有可预约位置。",
        "更换餐厅、调整餐段，或把餐厅改成备选槽位。",
    ),
    "route_timeout": (
        "error",
        "地点之间移动时间过长，路线不可执行。",
        "优先选择同商圈或 5 公里内候选，减少跨区移动。",
    ),
    "total_duration_exceeded": (
        "error",
        "方案总时长超过用户可用时间。",
        "压缩停留时长、减少一个槽位，或延长可用时间。",
    ),
    "budget_exceeded": (
        "error",
        "方案预算超过用户预算。",
        "降低价格等级，或减少高价活动/餐饮。",
    ),
    "poi_closed": (
        "error",
        "存在明确未营业的地点。",
        "替换为营业中的候选，或调整出发时间。",
    ),
    "duplicate_category": (
        "warning",
        "方案中同类地点重复较多，体验可能单一。",
        "增加餐饮、活动、休闲等不同类型的组合。",
    ),
    "cross_district_move": (
        "warning",
        "方案存在跨区移动，周末执行风险较高。",
        "优先选择同商圈、同区或交通更直接的地点。",
    ),
    "queue_risk": (
        "warning",
        "存在排队或拥挤风险。",
        "提前预约，或准备同类型备选地点。",
    ),
    "reservation_required": (
        "warning",
        "方案中有地点需要预约或购票确认。",
        "执行前确认库存、场次或预约时间。",
    ),
    "open_time_unknown": (
        "warning",
        "部分地点营业时间不明确。",
        "出发前再次确认营业状态。",
    ),
    "weak_preference_match": (
        "warning",
        "部分候选和用户明确偏好匹配较弱。",
        "降低该候选排序，或换成更匹配的类别。",
    ),
}


def make_issue(
    code: str,
    *,
    message: str | None = None,
    suggestion: str | None = None,
    severity: str | None = None,
    source: str = "",
    details: dict[str, Any] | None = None,
    target_plan_id: str | None = None,
    target_item_id: str | None = None,
) -> Issue:
    """创建统一的 Verifier / Critic 问题对象。

    顶层 `target_plan_id` 和 `target_item_id` 供前端直接定位方案或地点；`details`
    保留调试上下文，避免 UI 解析嵌套字段才能知道哪个对象出了问题。
    """

    default_severity, default_message, default_suggestion = ISSUE_DEFAULTS.get(
        code,
        ("error", code, "请调整约束后重试。"),
    )
    issue_details = details or {}
    inferred_plan_id = target_plan_id or _optional_str(issue_details.get("plan_id"))
    inferred_item_id = target_item_id or _optional_str(
        issue_details.get("poi_id") or issue_details.get("item_id")
    )
    return {
        "code": code,
        "message": message or default_message,
        "suggestion": suggestion or default_suggestion,
        "severity": severity or default_severity,
        "source": source,
        "target_plan_id": inferred_plan_id,
        "target_item_id": inferred_item_id,
        "details": issue_details,
    }


def normalize_issue(value: Any) -> Issue:
    """兼容旧字符串/旧 dict 错误，把它们归一为结构化 issue。"""

    if isinstance(value, dict):
        code = str(value.get("code") or "unknown_error")
        details = value.get("details") if isinstance(value.get("details"), dict) else {}
        return make_issue(
            code,
            message=value.get("message"),
            suggestion=value.get("suggestion"),
            severity=value.get("severity"),
            source=str(value.get("source") or ""),
            details=details,
            target_plan_id=_optional_str(value.get("target_plan_id")),
            target_item_id=_optional_str(value.get("target_item_id")),
        )
    text = str(value)
    if text.startswith("poi_closed:"):
        return make_issue(
            "poi_closed",
            source="availability_checker",
            details={"poi_id": text.split(":", 1)[1]},
        )
    return make_issue(text)


def normalize_issues(values: list[Any] | None) -> list[Issue]:
    """批量归一化 issue 对象。"""

    return [normalize_issue(value) for value in values or []]


def dedupe_issues(values: list[Any] | None) -> list[Issue]:
    """按 code/source/target/details 去重，同时保持出现顺序。"""

    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[Issue] = []
    for issue in normalize_issues(values):
        key = (
            str(issue.get("code")),
            str(issue.get("source")),
            str(issue.get("target_plan_id")),
            str(issue.get("target_item_id")),
            repr(sorted(issue.get("details", {}).items())),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def issue_codes(values: list[Any] | None) -> set[str]:
    """提取 issue code，供 Planner 做反馈策略判断。"""

    return {str(issue["code"]) for issue in normalize_issues(values)}


def has_blocking_issue(values: list[Any] | None) -> bool:
    """判断是否存在会阻断执行的 error 级问题。"""

    return any(issue.get("severity") == "error" for issue in normalize_issues(values))


def format_issue_codes(values: list[Any] | None) -> str:
    """日志中展示问题 code，避免把完整 JSON 打进日志。"""

    codes = [str(issue["code"]) for issue in normalize_issues(values)]
    return ",".join(codes) if codes else "none"


def _optional_str(value: Any) -> str:
    """把可选 ID 规整成字符串；缺失时保持空字符串，便于 JSON 输出稳定。"""

    return "" if value is None else str(value)

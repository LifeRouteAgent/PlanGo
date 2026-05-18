from __future__ import annotations

import re

from app.agents.llm_understanding import get_llm_understanding
from app.state.plan_state import PlanState, PlanStatePatch


def constraint_builder_node(state: PlanState) -> PlanStatePatch:
    query = state["user_query"]
    llm_understanding = get_llm_understanding(state)
    constraints = dict(state.get("constraints", {}))
    constraints.setdefault("city", state.get("user_profile", {}).get("city", "北京"))
    constraints.setdefault("start_time", _llm_or_default(llm_understanding, "start_time", _parse_start_time(query)))
    constraints.setdefault(
        "duration_hours",
        _llm_or_default(llm_understanding, "duration_hours", _parse_duration_hours(query)),
    )
    constraints.setdefault("budget", _llm_or_default(llm_understanding, "budget", _parse_budget(query)))
    if llm_understanding and llm_understanding.get("location_area"):
        constraints.setdefault("location_area", llm_understanding["location_area"])
    constraints.setdefault("max_route_minutes", 45)

    return {
        "constraints": constraints,
        "logs": [
            "Constraint Builder: normalized city, time window, budget, and route constraints"
            + (" with LLM values" if llm_understanding else " with rule fallback")
        ],
    }


def _llm_or_default(llm_understanding: dict | None, key: str, default: object) -> object:
    """优先使用大模型抽取出的约束；为空时使用规则解析或默认值。"""

    if not llm_understanding:
        return default
    value = llm_understanding.get(key)
    return default if value in {None, ""} else value


def _parse_start_time(text: str) -> str:
    match = re.search(r"(\d{1,2})\s*[:点]\s*(\d{2})?", text)
    if match:
        hour = _normalize_hour_by_period(int(match.group(1)), text)
        minute = int(match.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"
    if "上午" in text:
        return "10:00"
    if "晚上" in text:
        return "18:00"
    return "14:00"


def _parse_duration_hours(text: str) -> int:
    range_hours = _parse_time_range_hours(text)
    if range_hours:
        return range_hours

    match = re.search(r"(\d+)\s*(小时|个小时)", text)
    if match:
        return int(match.group(1))
    return 6


def _parse_budget(text: str) -> int:
    match = re.search(r"预算\s*(\d+)|(\d+)\s*元", text)
    if match:
        return int(match.group(1) or match.group(2))
    return 600


def _parse_time_range_hours(text: str) -> int | None:
    """从“下午 2 点到 6 点”这类表达中解析可用时长。

    本地生活规划对短时间窗口非常敏感，如果只使用默认 6 小时，
    Route Planner 会错误地安排过多活动。这里先支持常见的中文时间范围，
    后续可以再扩展到具体日期和分钟级时间。
    """

    match = re.search(
        r"(\d{1,2})\s*(?:[:点]\s*(\d{2})?)?\s*(?:到|至|-|~)\s*(\d{1,2})\s*(?:[:点]\s*(\d{2})?)?",
        text,
    )
    if not match:
        return None

    start_hour = _normalize_hour_by_period(int(match.group(1)), text)
    start_minute = int(match.group(2) or 0)
    end_hour = _normalize_hour_by_period(int(match.group(3)), text)
    end_minute = int(match.group(4) or 0)

    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total:
        # “晚上 8 点到 1 点”这类跨午夜表达先按次日处理。
        end_total += 24 * 60

    duration_minutes = end_total - start_total
    # 当前 PlanState 仍使用小时粒度；不足一小时按 1 小时兜底，避免返回 0。
    return max(1, round(duration_minutes / 60))


def _normalize_hour_by_period(hour: int, text: str) -> int:
    """根据上午/下午/晚上修正 12 小时制表达。"""

    if any(keyword in text for keyword in ("下午", "晚上", "今晚")) and 1 <= hour <= 11:
        return hour + 12
    return hour

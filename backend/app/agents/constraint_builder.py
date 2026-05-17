from __future__ import annotations

import re

from app.state.plan_state import PlanState, PlanStatePatch


def constraint_builder_node(state: PlanState) -> PlanStatePatch:
    query = state["user_query"]
    constraints = dict(state.get("constraints", {}))
    constraints.setdefault("city", state.get("user_profile", {}).get("city", "北京"))
    constraints.setdefault("start_time", _parse_start_time(query))
    constraints.setdefault("duration_hours", _parse_duration_hours(query))
    constraints.setdefault("budget", _parse_budget(query))
    constraints.setdefault("max_route_minutes", 45)

    return {
        "constraints": constraints,
        "logs": [
            "Constraint Builder: normalized city, time window, budget, and route constraints"
        ],
    }


def _parse_start_time(text: str) -> str:
    match = re.search(r"(\d{1,2})[:点](\d{2})?", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"
    if "上午" in text:
        return "10:00"
    if "晚上" in text:
        return "18:00"
    return "14:00"


def _parse_duration_hours(text: str) -> int:
    match = re.search(r"(\d+)\s*(小时|个小时)", text)
    if match:
        return int(match.group(1))
    return 6


def _parse_budget(text: str) -> int:
    match = re.search(r"预算\s*(\d+)|(\d+)\s*元", text)
    if match:
        return int(match.group(1) or match.group(2))
    return 600

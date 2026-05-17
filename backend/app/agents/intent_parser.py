from __future__ import annotations

import re

from app.state.plan_state import PlanState, PlanStatePatch


def intent_parser_node(state: PlanState) -> PlanStatePatch:
    query = state["user_query"]
    people_count = _parse_people_count(query)
    scenario = _parse_scenario(query)
    preferences = _parse_preferences(query)

    return {
        "constraints": {
            **state.get("constraints", {}),
            "scenario": scenario,
            "people_count": people_count,
            "preferences": preferences,
        },
        "logs": [f"Intent Parser: scenario={scenario}, people_count={people_count}"],
    }


def _parse_people_count(text: str) -> int:
    match = re.search(r"(\d+)\s*(个人|人|位)", text)
    if match:
        return int(match.group(1))
    if "一家" in text or "家庭" in text:
        return 3
    if "朋友" in text:
        return 2
    return 1


def _parse_scenario(text: str) -> str:
    if any(keyword in text for keyword in ("家庭", "孩子", "亲子", "小孩")):
        return "family"
    if any(keyword in text for keyword in ("朋友", "同学", "同事")):
        return "friends"
    if any(keyword in text for keyword in ("情侣", "约会", "女朋友", "男朋友")):
        return "couple"
    return "unknown"


def _parse_preferences(text: str) -> list[str]:
    mapping = {
        "餐厅": ("吃", "餐厅", "美食", "饭"),
        "活动": ("活动", "体验", "展", "票"),
        "休闲娱乐": ("电影", "KTV", "娱乐", "桌游"),
        "健身": ("健身", "运动", "瑜伽"),
        "美容养生": ("按摩", "美容", "养生", "足疗"),
        "购物": ("购物", "商场", "逛街"),
    }
    return [label for label, keywords in mapping.items() if any(k in text for k in keywords)]

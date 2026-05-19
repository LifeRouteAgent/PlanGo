from __future__ import annotations

import re

from app.agents.llm_understanding import get_llm_understanding
from app.state.plan_state import PlanState, PlanStatePatch


def intent_parser_node(state: PlanState) -> PlanStatePatch:
    query = state["user_query"]
    llm_understanding = get_llm_understanding(state)
    if llm_understanding:
        people_count = llm_understanding.get("people_count") or _parse_people_count(query)
        scenario = llm_understanding.get("scenario") or _parse_scenario(query)
        preferences = llm_understanding.get("preferences") or _parse_preferences(query)
        source = "LLM"
    else:
        people_count = _parse_people_count(query)
        scenario = _parse_scenario(query)
        preferences = _parse_preferences(query)
        source = "rule fallback"

    return {
        "constraints": {
            **state.get("constraints", {}),
            "scenario": scenario,
            "people_count": people_count,
            "preferences": preferences,
        },
        "logs": [f"Intent Parser: used {source}, scenario={scenario}, people_count={people_count}"],
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
        "休闲娱乐": (
            "电影",
            "KTV",
            "ktv",
            "娱乐",
            "桌游",
            "棋牌",
            "麻将",
            "打牌",
            "唱歌",
            "K歌",
            "k歌",
        ),
        "健身": ("健身", "运动", "瑜伽"),
        "美容养生": ("按摩", "美容", "养生", "足疗"),
        "购物": ("购物", "商场", "逛街"),
    }
    return [label for label, keywords in mapping.items() if any(k in text for k in keywords)]

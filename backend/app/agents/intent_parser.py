from __future__ import annotations

import re

from app.agents.llm_understanding import get_llm_understanding
from app.state.plan_state import PlanState, PlanStatePatch


def intent_parser_node(state: PlanState) -> PlanStatePatch:
    """从用户输入中抽取场景、人数和偏好。"""

    query = state["user_query"]
    llm_understanding = get_llm_understanding(state)
    if llm_understanding:
        people_count = llm_understanding.get("people_count") or _parse_people_count(query)
        scenario = llm_understanding.get("scenario") or _parse_scenario(query)
        if scenario in {None, "", "unknown"}:
            scenario = _parse_scenario(query)
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
    for match in re.finditer(r"(\d+)", text):
        suffix = text[match.end() : match.end() + 2]
        if suffix.startswith("个") or suffix.startswith("人") or suffix.startswith("位"):
            return int(match.group(1))
    chinese_count = _parse_chinese_people_count(text)
    if chinese_count:
        return chinese_count
    if "一家" in text or "家庭" in text:
        return 3
    if any(keyword in text for keyword in ("朋友", "对象", "情侣", "女朋友", "男朋友")):
        return 2
    return 1


def _parse_scenario(text: str) -> str:
    if any(keyword in text for keyword in ("家庭", "孩子", "亲子", "小孩")):
        return "family"
    if any(keyword in text for keyword in ("朋友", "同学", "同事")):
        return "friends"
    if any(keyword in text for keyword in ("对象", "情侣", "约会", "女朋友", "男朋友")):
        return "couple"
    return "unknown"


def _parse_preferences(text: str) -> list[str]:
    mapping = {
        "餐厅": ("吃", "餐厅", "美食", "饭", "晚餐", "午餐"),
        "活动": ("活动", "体验", "展览", "票券", "手作"),
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
        "健身": ("健身", "运动", "瑜伽", "羽毛球", "攀岩"),
        "美容养生": ("按摩", "美容", "养生", "足疗", "SPA", "spa"),
        "购物": ("购物", "商场", "逛街", "商圈"),
        "景点": ("环球影城", "景点", "乐园", "主题公园", "公园", "citywalk"),
    }
    preferences = [label for label, keywords in mapping.items() if any(k in text for k in keywords)]
    return list(dict.fromkeys(preferences))


def _parse_chinese_people_count(text: str) -> int | None:
    """解析“两个人/两位/四人”等中文人数表达。"""

    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "俩": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
    }
    for word, count in mapping.items():
        if f"{word}个人" in text or f"{word}人" in text or f"{word}位" in text:
            return count
    return None

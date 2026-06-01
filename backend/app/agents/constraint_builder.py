from __future__ import annotations

import re
from typing import Any

from app.agents.llm_understanding import get_llm_understanding
from app.state.plan_state import PlanState, PlanStatePatch


def constraint_builder_node(state: PlanState) -> PlanStatePatch:
    """把自然语言理解结果转成可执行约束，并记录每个约束的来源。

    这里最重要的规则是：默认值只能帮助系统生成一个可展示的初版方案，
    不能被 Verifier 当成用户明确给出的硬性限制。比如用户只说“明天”，
    系统可以暂按上午开始排时间线，但不能因为默认 6 小时或默认 45 分钟路程
    就判定方案不可执行。
    """

    query = state["user_query"]
    llm_understanding = get_llm_understanding(state)
    constraints = dict(state.get("constraints", {}))
    user_profile = state.get("user_profile", {})
    if llm_understanding and llm_understanding.get("scenario"):
        constraints.setdefault("scenario", llm_understanding["scenario"])
    else:
        constraints.setdefault("scenario", _fallback_scenario(query))

    constraints.setdefault(
        "city", user_profile.get("city") or user_profile.get("preferred_city") or "北京"
    )

    start_time, start_source = _resolve_start_time(query, llm_understanding)
    constraints.setdefault("start_time", start_time)
    constraints.setdefault("start_time_source", start_source)

    duration_hours, duration_source = _resolve_duration_hours(query, llm_understanding)
    constraints.setdefault("duration_hours", duration_hours)
    constraints.setdefault("duration_source", duration_source)
    constraints.setdefault("duration_is_hard", duration_source in {"llm", "fallback_rule"})

    budget, budget_source = _resolve_budget(query, llm_understanding)
    constraints.setdefault("budget", budget)
    constraints.setdefault("budget_source", budget_source)
    constraints.setdefault("budget_is_hard", budget_source in {"llm", "fallback_rule"})

    max_route_minutes, route_source = _resolve_max_route_minutes(query, llm_understanding)
    constraints.setdefault("max_route_minutes", max_route_minutes)
    constraints.setdefault("max_route_minutes_source", route_source)
    constraints.setdefault("route_limit_is_hard", route_source in {"llm", "fallback_rule"})

    if llm_understanding and llm_understanding.get("location_area"):
        constraints.setdefault("location_area", llm_understanding["location_area"])
    must_keywords = _must_keywords_from_llm(llm_understanding)
    if not must_keywords:
        must_keywords = _extract_must_keywords(query)
    if must_keywords:
        constraints.setdefault("must_keywords", must_keywords)
    preference_keywords = _preference_keywords_from_llm(llm_understanding)
    if not preference_keywords:
        preference_keywords = _extract_preference_keywords(query)
    if preference_keywords:
        constraints.setdefault("preference_keywords", preference_keywords)
    activity_intents = _activity_intents_from_llm(llm_understanding)
    if activity_intents:
        constraints.setdefault("activity_intents", activity_intents)

    return {
        "constraints": constraints,
        "logs": [
            "Constraint Builder: normalized constraints with source flags "
            f"(start={constraints.get('start_time_source')}, "
            f"duration={constraints.get('duration_source')}, "
            f"budget={constraints.get('budget_source')}, "
            f"route={constraints.get('max_route_minutes_source')})"
        ],
    }


def _resolve_start_time(query: str, llm_understanding: dict[str, Any] | None) -> tuple[str, str]:
    if llm_understanding and llm_understanding.get("start_time"):
        return str(llm_understanding["start_time"]), "llm"
    parsed = _fallback_parse_start_time(query)
    if parsed:
        return parsed, "fallback_rule"
    if any(word in query for word in ("上午", "早上")):
        return "10:00", "fallback_rule"
    if any(word in query for word in ("晚上", "今晚")):
        return "18:00", "fallback_rule"
    # 默认值只用于排版时间线，不代表用户限定了下午 2 点。
    return "10:00", "default"


def _resolve_duration_hours(
    query: str, llm_understanding: dict[str, Any] | None
) -> tuple[int, str]:
    if llm_understanding and llm_understanding.get("duration_hours") not in (None, ""):
        return int(float(llm_understanding["duration_hours"])), "llm"
    parsed = _fallback_parse_duration_hours(query)
    if parsed is not None:
        return parsed, "fallback_rule"
    # 如果没有明确时长或起止时间，不接受 LLM 自行补出的 duration_hours。
    # 用较宽松的 10 小时作为本地一日活动排版窗口，但 Verifier 不把它当硬约束。
    return 10, "default"


def _resolve_budget(query: str, llm_understanding: dict[str, Any] | None) -> tuple[int, str]:
    if llm_understanding and llm_understanding.get("budget"):
        return int(float(llm_understanding["budget"])), "llm"
    parsed = _fallback_parse_budget(query)
    if parsed is not None:
        return parsed, "fallback_rule"
    return 600, "default"


def _resolve_max_route_minutes(
    query: str, llm_understanding: dict[str, Any] | None
) -> tuple[int, str]:
    explicit = _fallback_parse_route_minutes(query)
    if explicit is not None:
        return explicit, "fallback_rule"
    if any(word in query for word in ("别太远", "近一点", "附近", "少折腾", "少走路")):
        return 30, "fallback_rule"
    # 默认路程阈值只是排序偏好，不是失败条件。
    return 90, "system_default"


def _fallback_scenario(text: str) -> str:
    """LLM 不可用时的极小场景兜底。

    语义判断主路径仍然是 LLM；这里仅在模型失败、测试离线或输出缺失时保留
    “朋友/情侣/家庭”这类基础场景，避免后续 Planner 丢失关键上下文。
    """

    if any(keyword in text for keyword in ("朋友", "同学", "同事", "哥们", "闺蜜")):
        return "friends"
    if any(keyword in text for keyword in ("对象", "情侣", "女朋友", "男朋友", "约会")):
        return "couple"
    if any(keyword in text for keyword in ("家人", "家庭", "孩子", "亲子", "爸妈")):
        return "family"
    return "unknown"


def _fallback_parse_start_time(text: str) -> str | None:
    """LLM 不可用时解析明确钟点；正常路径应使用 LLM 结构化结果。"""

    match = re.search(r"(\d{1,2})\s*(?::|点|：)\s*(\d{2})?", text)
    if not match:
        return None
    hour = _normalize_hour_by_period(int(match.group(1)), text)
    minute = int(match.group(2) or 0)
    return f"{hour:02d}:{minute:02d}"


def _fallback_parse_duration_hours(text: str) -> int | None:
    """LLM 不可用时解析明确时长；正常路径应使用 LLM 结构化结果。"""

    range_hours = _fallback_parse_time_range_hours(text)
    if range_hours:
        return range_hours
    match = re.search(r"(\d+)\s*(小时|个小时)", text)
    if match:
        return int(match.group(1))
    if "半天" in text:
        return 4
    if "一天" in text or "一整天" in text:
        return 10
    return None


def _fallback_parse_budget(text: str) -> int | None:
    """LLM 不可用时的预算兜底解析。

    正常链路必须优先消费 `llm_understanding.budget`。这里仅用于模型不可用、
    schema 校验失败或离线测试，避免系统完全失去预算约束。
    """

    matches: list[tuple[int, float, str]] = []
    patterns = (
        r"(?:预算|预算是|预算为|预算改成|预算调整到|预算更正为)\s*(\d+(?:\.\d+)?)\s*([kK千wW万]?)",
        r"(\d+(?:\.\d+)?)\s*([kK千wW万]?)\s*(?:元|块|人民币)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            unit = match.group(2) or ""
            matches.append((match.start(), float(match.group(1)), unit))
    chinese_match = re.search(r"(?:预算|预算是|预算为|预算改成|预算调整到|预算更正为)\s*(一千|两千|二千|三千|四千|五千|六千|七千|八千|九千)", text)
    if chinese_match:
        mapping = {
            "一千": 1000,
            "两千": 2000,
            "二千": 2000,
            "三千": 3000,
            "四千": 4000,
            "五千": 5000,
            "六千": 6000,
            "七千": 7000,
            "八千": 8000,
            "九千": 9000,
        }
        matches.append((chinese_match.start(), float(mapping[chinese_match.group(1)]), ""))
    if not matches:
        return None
    _, amount, unit = sorted(matches, key=lambda item: item[0])[-1]
    multiplier = 1
    if unit in {"k", "K", "千"}:
        multiplier = 1000
    elif unit in {"w", "W", "万"}:
        multiplier = 10000
    return int(amount * multiplier)


def _fallback_parse_route_minutes(text: str) -> int | None:
    """LLM 不可用时解析明确路程上限；正常路径应使用 LLM/Revision 结构化结果。"""

    match = re.search(r"(?:路程|交通|移动|车程|通勤|路上)[^\d]{0,6}(\d+)\s*(?:分钟|分)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*(?:分钟|分)[^\n，。]{0,8}(?:路程|交通|移动|车程|通勤|路上)", text)
    if match:
        return int(match.group(1))
    if "半小时" in text and any(
        word in text for word in ("路程", "交通", "移动", "车程", "通勤", "路上")
    ):
        return 30
    return None


def _fallback_parse_time_range_hours(text: str) -> int | None:
    """LLM 不可用时解析“下午 2 点到 6 点”这类起止时间。"""

    match = re.search(
        r"(\d{1,2})\s*(?:(?:点|:|：)\s*(\d{2})?)?\s*(?:到|至|-|~)\s*"
        r"(\d{1,2})\s*(?:(?:点|:|：)\s*(\d{2})?)?",
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
        end_total += 24 * 60
    return max(1, round((end_total - start_total) / 60))


def _normalize_hour_by_period(hour: int, text: str) -> int:
    if any(keyword in text for keyword in ("下午", "晚上", "今晚")) and 1 <= hour <= 11:
        return hour + 12
    return hour


def _has_explicit_start_time(text: str) -> bool:
    return bool(
        re.search(r"\d{1,2}\s*(?::|点|：)", text)
        or any(word in text for word in ("上午", "早上", "下午", "晚上", "今晚"))
    )


def _has_budget(text: str) -> bool:
    return bool(re.search(r"预算\s*\d+|\d+\s*元", text))


def _extract_must_keywords(text: str) -> list[str]:
    """抽取用户明确点名“必须去”的地点关键词。

    v1 先覆盖本地生活规划里常见的专名表达，后续可以扩展成 NER 或地点词典。
    这些关键词会进入 Collector 的名称检索，并在 Route Planner 中强制带入方案。
    """

    known_places = (
        "环球影城",
        "北京环球影城",
        "北京环球度假区",
        "环球城市大道",
    )
    result = [place for place in known_places if place in text]
    if "环球影城" in text and "北京环球度假区" not in result:
        result.append("北京环球度假区")
    # 如果同时命中“北京环球影城”和“环球影城”，保留更长、更具体的词。
    deduped: list[str] = []
    for place in sorted(result, key=len, reverse=True):
        if not any(place in existing or existing in place for existing in deduped):
            deduped.append(place)
    return deduped


def _must_keywords_from_llm(llm_understanding: dict[str, Any] | None) -> list[str]:
    """优先使用 LLM 抽取的 must_pois 名称，规则只做兜底。"""

    if not llm_understanding:
        return []
    result: list[str] = []
    for item in llm_understanding.get("must_pois", []) or []:
        if isinstance(item, dict) and item.get("must_include", True):
            name = str(item.get("name") or "").strip()
            if name:
                result.append(name)
    return list(dict.fromkeys(result))


def _preference_keywords_from_llm(llm_understanding: dict[str, Any] | None) -> list[str]:
    """优先使用 LLM 抽取的偏好关键词和活动语义关键词。"""

    if not llm_understanding:
        return []
    result = [str(item).strip() for item in llm_understanding.get("preference_keywords", []) or [] if str(item).strip()]
    for intent in llm_understanding.get("activity_intents", []) or []:
        if isinstance(intent, dict):
            result.extend(str(item).strip() for item in intent.get("keywords", []) or [] if str(item).strip())
    return list(dict.fromkeys(result))


def _activity_intents_from_llm(llm_understanding: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把 LLM 活动语义类型透传到 Route Planner/Skill。"""

    if not llm_understanding:
        return []
    intents = llm_understanding.get("activity_intents", [])
    return [item for item in intents if isinstance(item, dict)]


def _extract_preference_keywords(text: str) -> list[str]:
    """抽取用户明确偏好的垂类关键词，用于补充召回但不强制进方案。"""

    mapping = {
        ("唱歌", "KTV", "ktv", "K歌", "k歌"): ["KTV", "量贩", "唱歌"],
        ("麻将", "打牌", "棋牌"): ["麻将", "棋牌", "桌游"],
        ("电影", "影院", "看电影"): ["电影", "影院", "影城"],
        ("密室",): ["密室"],
        ("剧本杀",): ["剧本杀"],
    }
    result: list[str] = []
    for query_keywords, poi_keywords in mapping.items():
        if any(keyword in text for keyword in query_keywords):
            result.extend(poi_keywords)
    return list(dict.fromkeys(result))

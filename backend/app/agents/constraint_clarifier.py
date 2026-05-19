from __future__ import annotations

import re

from app.agents.llm_understanding import get_llm_understanding
from app.state.plan_state import PlanState, PlanStatePatch


def constraint_clarifier_node(state: PlanState) -> PlanStatePatch:
    """约束完整性检查与追问节点。

    本地生活规划和普通 POI 推荐不同：如果用户只说“周末想出去玩”，
    直接生成路线会很容易给出不可执行方案。因此这里先判断输入是否具备
    足够的规划条件，缺失时只生成追问，不进入 Collector、Skill 和路线规划。

    设计原则：
    - 简单问答不会进入本节点。
    - 单类推荐只要求类别明确，允许预算/时间缺省。
    - 完整规划至少需要同行场景/人数、时间窗口、偏好类别三类核心信息。
    - 预算和位置可以先给默认值，但会在追问里作为可选补充提示。
    """

    intent_type = state.get("intent_type", "full_trip_plan")
    query = state["user_query"]
    constraints = state.get("constraints", {})
    llm_understanding = get_llm_understanding(state)

    if llm_understanding:
        rule_missing = _missing_constraints(intent_type, query, constraints)
        llm_missing = list(llm_understanding.get("missing_constraints", []))
        # 如果模型没有给出缺失项，但结构化结果也缺少规划核心字段，则使用规则护栏。
        # 这样可以避免模型把“周末想出去玩”这类模糊请求直接放行。
        if (
            intent_type == "full_trip_plan"
            and not llm_missing
            and rule_missing
            and not _llm_has_core_planning_fields(llm_understanding)
        ):
            missing = rule_missing
            need_clarification = True
            question = _build_clarify_question(missing)
            source = "rule guard after LLM"
        else:
            missing = llm_missing
            need_clarification = bool(llm_understanding.get("need_clarification")) and bool(missing)
            question = llm_understanding.get("clarify_question") or _build_clarify_question(missing)
            source = "LLM"
    else:
        missing = _missing_constraints(intent_type, query, constraints)
        need_clarification = bool(missing)
        question = _build_clarify_question(missing)
        source = "rule fallback"

    if not missing:
        return {
            "need_clarification": False,
            "missing_constraints": [],
            "clarify_question": "",
            "logs": [f"Constraint Clarifier: used {source}, enough information to continue"],
        }

    return {
        "need_clarification": need_clarification,
        "missing_constraints": missing,
        "clarify_question": question if need_clarification else "",
        "answer_mode": (
            "clarification" if need_clarification else state.get("answer_mode", "trip_plan")
        ),
        "logs": [
            f"Constraint Clarifier: used {source}, missing "
            + ",".join(missing)
            + (
                ", generated clarify question"
                if need_clarification
                else ", continue by LLM decision"
            )
        ],
    }


def constraint_clarifier_route(state: PlanState) -> str:
    """Clarifier 后的 DAG 条件边。

    需要追问时直接进入 Response Generator；信息足够时再继续 Planner。
    """

    return "clarify" if state.get("need_clarification") else "continue"


def _missing_constraints(
    intent_type: str,
    query: str,
    constraints: dict[str, object],
) -> list[str]:
    """按意图类型判断缺失字段。

    `constraint_builder` 会提供默认城市、默认时间和默认预算，所以这里不能只看
    constraints 字段是否存在，还要回到原始 query 判断用户是否真的表达了约束。
    """

    if intent_type in {"category_recommend", "poi_search"}:
        return [] if _has_category_or_preference(query, constraints) else ["preference"]

    if intent_type != "full_trip_plan":
        return []

    missing: list[str] = []
    if not _has_people_or_scenario(query, constraints):
        missing.append("people_or_scenario")
    if not _has_time_window(query):
        missing.append("time_window")
    if not _has_category_or_preference(query, constraints):
        missing.append("preference")
    return missing


def _llm_has_core_planning_fields(llm_understanding: dict[str, object]) -> bool:
    """判断模型是否真的抽取到了足够的完整规划核心信息。"""

    has_people_or_scenario = bool(llm_understanding.get("people_count")) or llm_understanding.get(
        "scenario"
    ) not in {None, "", "unknown"}
    has_time = bool(llm_understanding.get("start_time") or llm_understanding.get("duration_hours"))
    has_preference = bool(
        llm_understanding.get("preferences") or llm_understanding.get("target_categories")
    )
    return bool(has_people_or_scenario and has_time and has_preference)


def _has_people_or_scenario(query: str, constraints: dict[str, object]) -> bool:
    """判断用户是否说明了同行对象或人数。"""

    if constraints.get("scenario") not in {None, "", "unknown"}:
        return True
    if int(constraints.get("people_count") or 0) > 1:
        return True
    return bool(
        re.search(r"\d+\s*(个?人|位)", query)
        or any(
            keyword in query
            for keyword in ("朋友", "家庭", "亲子", "情侣", "同事", "同学", "老人", "孩子")
        )
    )


def _has_time_window(query: str) -> bool:
    """判断用户是否给出可规划的时间窗口或时长。"""

    return bool(
        re.search(r"\d+\s*(小时|个小时|分钟)", query)
        or re.search(r"\d{1,2}[:点]\d{0,2}", query)
        or any(
            keyword in query
            for keyword in ("上午", "下午", "晚上", "今晚", "明天", "周六", "周日", "半天", "一天")
        )
    )


def _has_category_or_preference(query: str, constraints: dict[str, object]) -> bool:
    """判断用户是否表达了活动偏好或目标类别。"""

    preferences = constraints.get("preferences")
    if isinstance(preferences, list) and preferences:
        return True
    return any(
        keyword in query
        for keyword in (
            "吃",
            "餐厅",
            "美食",
            "电影",
            "唱歌",
            "KTV",
            "ktv",
            "K歌",
            "k歌",
            "麻将",
            "打牌",
            "棋牌",
            "桌游",
            "娱乐",
            "展览",
            "活动",
            "逛街",
            "购物",
            "运动",
            "健身",
            "按摩",
            "养生",
            "公园",
            "citywalk",
        )
    )


def _build_clarify_question(missing: list[str]) -> str:
    """把缺失字段转成面向用户的一次性追问。"""

    parts: list[str] = []
    if "people_or_scenario" in missing:
        parts.append("和谁一起去、大概几个人")
    if "time_window" in missing:
        parts.append("可用时间或希望控制在几个小时内")
    if "preference" in missing:
        parts.append("更偏吃饭、电影、展览、逛街、运动还是放松养生")

    joined = "、".join(parts)
    return (
        f"为了给你生成可执行的本地生活方案，还需要确认：{joined}。也可以顺便告诉我预算和出发区域。"
    )

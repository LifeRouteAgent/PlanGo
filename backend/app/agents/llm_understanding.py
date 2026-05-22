from __future__ import annotations

from typing import Any

from app.services.context_builder import ContextBuilder
from app.services.llm_service import call_chat_completion, extract_json_object
from app.tools.poi_schema import (
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_BEAUTY,
    POI_ENTERTAINMENT,
    POI_FITNESS,
    POI_RESTAURANT,
    POI_SHOPPING,
)

ALLOWED_INTENTS = {
    "capability",
    "simple_qa",
    "category_recommend",
    "poi_search",
    "full_trip_plan",
}

ALLOWED_CATEGORIES = {
    POI_RESTAURANT,
    POI_ACTIVITY,
    POI_ATTRACTION,
    POI_SHOPPING,
    POI_FITNESS,
    POI_ENTERTAINMENT,
    POI_BEAUTY,
}

ALLOWED_TEMPLATES = {
    "meal_only",
    "meal_plus_activity",
    "family_half_day",
    "friends_gathering",
    "entertainment_gathering",
    "couple_date",
    "relaxation",
    "shopping_leisure",
    "category_recommendation",
}

ALLOWED_MISSING = {"people_or_scenario", "time_window", "preference", "location", "budget"}


def get_llm_understanding(state: dict[str, Any]) -> dict[str, Any] | None:
    """读取已经缓存到 PlanState.constraints 的大模型理解结果。"""

    understanding = state.get("constraints", {}).get("llm_understanding")
    return understanding if isinstance(understanding, dict) else None


def build_llm_understanding(
    query: str, user_profile: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """用大模型完成意图识别、约束抽取、追问判断和规划模板选择。

    该函数只负责“理解用户输入”，不访问数据库，也不生成不存在的 POI。
    如果模型不可用或输出不合规，返回 None，让调用方使用规则兜底。
    """

    profile = user_profile or {}
    messages = [
        {
            "role": "system",
            "content": (
                "你是本地生活规划系统的意图与约束理解器。"
                "你只做结构化理解，不要推荐具体商家，不要编造 POI、路线、价格或营业信息。"
                "必须只输出一个 JSON 对象，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": _build_prompt(query, profile),
        },
    ]
    # 结构化理解 prompt 较长，MiMo 还可能返回 reasoning_content。
    # 这里给足输出预算，避免 JSON 被截断后触发规则兜底。
    raw = call_chat_completion(
        messages, temperature=0.0, timeout_seconds=60, max_completion_tokens=2048
    )
    parsed = extract_json_object(raw)
    return _normalize_understanding(parsed) if parsed else None


def _build_prompt(query: str, user_profile: dict[str, Any]) -> str:
    """构造稳定的结构化抽取 prompt。"""

    return f"""
请理解用户的本地生活需求，并输出 JSON。

用户输入：
{query}

用户画像：
{ContextBuilder().build_user_profile_context(user_profile)}

可选 intent_type：
- capability：询问系统能力或怎么使用
- simple_qa：普通闲聊/解释类问题，不需要查库和规划
- category_recommend：只要求推荐某一类地点，例如餐厅、KTV、按摩
- poi_search：查找某类地点或附近地点，但不要求排序规划
- full_trip_plan：需要把多个活动或一个时间窗口组织成可执行安排

可选 target_categories：
- poi_restaurant
- poi_activity
- poi_attraction
- poi_shopping
- poi_fitness
- poi_entertainment
- poi_beauty

可选 planning_template：
- meal_only
- meal_plus_activity
- family_half_day
- friends_gathering
- entertainment_gathering
- couple_date
- relaxation
- shopping_leisure
- category_recommendation

完整规划是否需要追问的判断：
- 如果用户已经说明同行对象/人数、时间窗口或时长、活动偏好，则 need_clarification=false。
- 预算和位置缺失可以使用默认值，不要因为只缺预算或位置就追问。
- 只有缺少导致无法执行规划的核心信息时才追问。

请输出如下 JSON 字段：
{{
  "intent_type": "full_trip_plan",
  "target_categories": ["poi_entertainment"],
  "scenario": "friends",
  "people_count": 2,
  "preferences": ["麻将", "唱歌"],
  "location_area": null,
  "start_time": "10:00",
  "duration_hours": 4,
  "budget": 200,
  "planning_template": "entertainment_gathering",
  "required_slots": ["entertainment", "optional_entertainment"],
  "need_clarification": false,
  "missing_constraints": [],
  "clarify_question": ""
}}
"""


def _normalize_understanding(data: dict[str, Any]) -> dict[str, Any] | None:
    """校验并规整模型输出，避免不合法字段污染 PlanState。"""

    intent_type = str(data.get("intent_type") or "").strip()
    if intent_type not in ALLOWED_INTENTS:
        return None

    categories = [
        str(item) for item in data.get("target_categories", []) if str(item) in ALLOWED_CATEGORIES
    ]
    preferences = _clean_string_list(data.get("preferences"))
    if not _has_readable_preference(preferences):
        preferences = _preferences_for_categories(categories)
    template = str(data.get("planning_template") or "").strip()
    if template and template not in ALLOWED_TEMPLATES:
        template = ""

    missing = [
        str(item) for item in data.get("missing_constraints", []) if str(item) in ALLOWED_MISSING
    ]

    normalized: dict[str, Any] = {
        "intent_type": intent_type,
        "target_categories": categories,
        "scenario": _clean_optional_string(data.get("scenario")) or "unknown",
        "people_count": _clean_int(data.get("people_count")),
        "preferences": preferences,
        "location_area": _clean_optional_string(data.get("location_area")),
        "start_time": _clean_optional_string(data.get("start_time")),
        "duration_hours": _clean_number(data.get("duration_hours")),
        "budget": _clean_int(data.get("budget")),
        "planning_template": template,
        "required_slots": _clean_string_list(data.get("required_slots")),
        "need_clarification": bool(data.get("need_clarification")),
        "missing_constraints": missing,
        "clarify_question": _clean_optional_string(data.get("clarify_question")) or "",
    }
    return normalized


def _clean_optional_string(value: Any) -> str | None:
    """清洗模型返回的可选字符串。"""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_string_list(value: Any) -> list[str]:
    """清洗模型返回的字符串列表。"""

    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _has_readable_preference(preferences: list[str]) -> bool:
    """判断模型返回的偏好词是否可读。

    MiMo 在少数中文抽取场景下可能把偏好词输出成乱码或其他文字系统。
    这类值不适合进入 PlanState，后续用目标类别映射出的中文偏好兜底。
    """

    return any(
        any("\u4e00" <= char <= "\u9fff" or (char.isascii() and char.isalnum()) for char in item)
        for item in preferences
    )


def _preferences_for_categories(categories: list[str]) -> list[str]:
    """根据统一 POI 类别生成稳定的中文偏好标签。"""

    mapping = {
        POI_RESTAURANT: "餐厅",
        POI_ACTIVITY: "活动",
        POI_ATTRACTION: "景点",
        POI_SHOPPING: "购物",
        POI_FITNESS: "健身",
        POI_ENTERTAINMENT: "休闲娱乐",
        POI_BEAUTY: "美容养生",
    }
    return [mapping[category] for category in categories if category in mapping]


def _clean_int(value: Any) -> int | None:
    """把模型返回的数字字段规整成 int。"""

    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_number(value: Any) -> float | None:
    """把模型返回的时长字段规整成数字。"""

    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

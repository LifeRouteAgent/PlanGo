from __future__ import annotations

import json
from typing import Any

from app.services.context_builder import ContextBuilder
from app.services.llm_service import call_chat_completion, extract_json_object
from app.services.llm_output_schemas import IntentUnderstandingOutput, validate_llm_output
from app.services.prompt_registry import load_prompt_template
from app.services.trace_recorder import record_trace_event
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

ALLOWED_SKILLS = {
    "poi_mix_recommend",
    "poi_activity_recommend",
    "poi_restaurant_recommend",
    "poi_lifestyle_recommend",
}

ALLOWED_MOVEMENT_POLICIES = {
    "balanced_local",
    "low_movement",
    "compact_walk_or_taxi",
    "same_business_area_first",
}

ALLOWED_CANDIDATE_STRATEGIES = {
    "slot_balance",
    "same_business_area_first",
    "restaurant_fit_first",
    "slow_pace_reservation_first",
    "category_focus",
    "preference_fit_first",
    "budget_fit_first",
    "compact_slots_same_area_first",
}


def get_llm_understanding(state: dict[str, Any]) -> dict[str, Any] | None:
    """读取 Intent Router 写入 PlanState.constraints 的 LLM 结构化理解结果。"""

    understanding = state.get("constraints", {}).get("llm_understanding")
    return understanding if isinstance(understanding, dict) else None


def build_llm_understanding(
    query: str,
    user_profile: dict[str, Any] | None = None,
    *,
    conversation_context: dict[str, Any] | None = None,
    poi_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """调用大模型做意图识别、约束抽取、追问判断和规划模板选择。

    这个函数只负责理解输入，不访问数据库，也不生成具体 POI、路线、价格或营业信息。
    如果模型不可用或输出不合规，返回 None，让调用方走确定性规则兜底。
    """

    profile = user_profile or {}
    messages = [
        {
            "role": "system",
            "content": load_prompt_template(
                "intent_understanding",
                "你是本地生活规划系统的意图与约束理解器。"
                "你只做结构化理解，不推荐具体商家，不编造 POI、路线、价格或营业信息。"
                "必须只输出一个 JSON 对象，不要输出 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": _build_prompt(
                query,
                profile,
                conversation_context or {},
                poi_knowledge=poi_knowledge or {},
            ),
        },
    ]
    raw = call_chat_completion(
        messages,
        temperature=0.0,
        timeout_seconds=60,
        max_completion_tokens=2048,
        prompt_name="intent_understanding",
        schema_name="IntentUnderstandingOutput",
    )
    parsed = extract_json_object(raw)
    validation = (
        validate_llm_output(IntentUnderstandingOutput, parsed, source="intent_understanding")
        if isinstance(parsed, dict)
        else None
    )
    normalized = _normalize_understanding(validation.data) if validation and validation.ok else None
    record_trace_event(
        "llm_understanding",
        {
            "success": bool(normalized),
            "schema_valid": bool(validation and validation.ok),
            "raw_preview": raw[:600] if raw else "",
            "understanding": normalized or {},
        },
    )
    return normalized


def _build_prompt(
    query: str,
    user_profile: dict[str, Any],
    conversation_context: dict[str, Any] | None = None,
    *,
    poi_knowledge: dict[str, Any] | None = None,
) -> str:
    """构造稳定的结构化抽取 prompt。

    用户画像和 Memory 只能作为软偏好，不能被模型复制成“本轮用户明确说过的约束”。
    """

    context_builder = ContextBuilder()
    profile_context = context_builder.build_user_profile_context(user_profile)
    context_snapshot = context_builder.build_for(
        "intent_router",
        {
            "user_query": query,
            "user_profile": user_profile,
            "conversation_context": conversation_context or {},
            "constraints": {},
            "dag_plan": {},
            "candidate_pois": {},
            "recommended_pois": {},
            "ranked_plans": [],
            "errors": [],
            "logs": [],
            "poi_knowledge": poi_knowledge or {},
        },
    )
    return f"""
请理解用户的本地生活需求，并且只输出一个 JSON 对象。

用户本轮输入（当前任务描述，不等同于完整聊天历史）：
{query}

最近对话/上一轮规划上下文（用于判断是否续跑；直接问答时必须忽略规划上下文）：
{json.dumps(conversation_context or {}, ensure_ascii=False, default=str)}

历史画像和记忆（只能作为软偏好，不得覆盖本轮输入）：
{profile_context}

结构化上下文快照（这是唯一允许参考的规划上下文，不要自行回忆完整聊天历史）：
{json.dumps(context_snapshot, ensure_ascii=False, default=str)}

关键规则：
1. intent_type 可选：
   - capability：询问系统能力、怎么使用。
   - simple_qa：普通闲聊、模型身份、解释类问题，不需要查库和规划。
   - category_recommend：只要求推荐某一类地点，例如餐厅、KTV、按摩。
   - poi_search：查找某类地点或附近地点，但不要求排时间线。
   - full_trip_plan：需要把多个活动或一个时间窗口组织成可执行安排。
2. 如果本轮输入是“你是什么模型/你支持什么功能/怎么使用”，必须输出 simple_qa 或 capability，不要沿用历史规划。
3. 如果本轮输入是“预算改成1000”“两个人，预算1000”“其他不变”“继续刚才方案”这类补充/更正，并且 conversation_context 里存在 pending_clarification_query 或 latest_planning_query，必须基于上下文合并成完整规划理解，通常输出 full_trip_plan，不要当成 simple_qa。
4. 如果用户说“环球影城然后唱歌”“吃饭再看电影”这类多个活动组合，通常是 full_trip_plan。
5. 如果用户已经说明同行对象或人数、日期/时间线索、活动偏好，就不要追问。
6. 预算和出发区域可以缺省，不要只因为缺预算或缺位置追问。
7. start_time 和 duration_hours 只有用户明确说了钟点、上午/下午/晚上、几小时、半天、一天或起止时间时才填写；不要自行补 14:00 或 6 小时。
8. 历史画像里的室内、低预算、常去区域只能影响后续排序，不得写入 preferences，除非本轮用户明确提到。
9. budget 必须做语义归一化：预算1k/1K/一千=1000，0.8万=8000；如果上下文和本轮输入里出现预算更正，以本轮输入为准。
10. category_tag_requirements 中的标签只能从 POI 标签背景知识对应类别的 available_tags 中选择，必须使用完全一致的标签名称，不得编造。
11. 用户明确偏好的标签写入 positive_logic_tags；明确排除的标签写入 negative_logic_tags。target_slot 填该标签作用的规划槽位。

target_categories 可选：
- poi_restaurant
- poi_activity
- poi_attraction
- poi_shopping
- poi_fitness
- poi_entertainment
- poi_beauty

planning_template 可选：
- meal_only
- meal_plus_activity
- family_half_day
- friends_gathering
- entertainment_gathering
- couple_date
- relaxation
- shopping_leisure
- category_recommendation

请输出这些字段：
{{
  "intent_type": "full_trip_plan",
  "target_categories": ["poi_attraction", "poi_entertainment"],
  "scenario": "couple",
  "people_count": 2,
  "preferences": ["环球影城", "唱歌"],
  "location_area": null,
  "start_time": null,
  "duration_hours": null,
  "budget": 1000,
  "planning_template": "couple_date",
  "required_slots": ["attraction", "entertainment"],
  "must_pois": [
    {{"name": "北京环球度假区", "category": "poi_attraction", "must_include": true}}
  ],
  "preference_keywords": ["KTV"],
  "activity_intents": [
    {{"slot": "entertainment", "semantic_type": "ktv", "must_match": true, "keywords": ["KTV", "唱歌"]}}
  ],
  "category_tag_requirements": [
    {{"logical_category": "entertainment", "target_slot": "entertainment", "positive_logic_tags": ["KTV"], "negative_logic_tags": []}}
  ],
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
    required_slots = _clean_string_list(data.get("required_slots"))

    missing = [
        str(item) for item in data.get("missing_constraints", []) if str(item) in ALLOWED_MISSING
    ]

    return {
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
        "required_slots": required_slots,
        "must_pois": _clean_must_pois(data.get("must_pois")),
        "preference_keywords": _clean_string_list(data.get("preference_keywords")),
        "activity_intents": _clean_activity_intents(data.get("activity_intents")),
        "category_tag_requirements": _clean_category_tag_requirements(data.get("category_tag_requirements")),
        "dag_plan": _clean_dag_plan(data.get("dag_plan"), template, required_slots, categories),
        "need_clarification": bool(data.get("need_clarification")),
        "missing_constraints": missing,
        "clarify_question": _clean_optional_string(data.get("clarify_question")) or "",
    }


def _clean_must_pois(value: Any) -> list[dict[str, Any]]:
    """清洗 LLM 抽取的明确必去地点。"""

    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_optional_string(item.get("name"))
        if not name:
            continue
        category = str(item.get("category") or "").strip()
        result.append({
            "name": name,
            "category": category if category in ALLOWED_CATEGORIES else "",
            "must_include": bool(item.get("must_include", True)),
        })
    return result[:5]


def _clean_activity_intents(value: Any) -> list[dict[str, Any]]:
    """清洗 LLM 抽取的活动语义类型。"""

    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        semantic_type = _clean_optional_string(item.get("semantic_type"))
        if not semantic_type:
            continue
        result.append({
            "slot": _clean_optional_string(item.get("slot")) or "",
            "semantic_type": semantic_type,
            "must_match": bool(item.get("must_match")),
            "keywords": _clean_string_list(item.get("keywords"))[:8],
        })
    return result[:8]


def _clean_category_tag_requirements(value: Any) -> list[dict[str, Any]]:
    """Clean category-specific tag mappings; catalog validation happens in V2 intent resolver."""

    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        category = _clean_optional_string(item.get("logical_category"))
        if not category:
            continue
        result.append({
            "logical_category": category,
            "target_slot": _clean_optional_string(item.get("target_slot")) or category,
            "positive_logic_tags": _clean_string_list(item.get("positive_logic_tags"))[:12],
            "negative_logic_tags": _clean_string_list(item.get("negative_logic_tags"))[:12],
        })
    return result[:12]


def _clean_dag_plan(
    value: Any,
    fallback_template: str,
    fallback_slots: list[str],
    fallback_categories: list[str],
) -> dict[str, Any]:
    """清洗 LLM 生成的 DAG Plan。

    LLM 可以决定本轮需要查哪些类别、启用哪些 Skill、采用什么规划模板；代码只做
    白名单校验和默认值兜底，避免模型输出污染 LangGraph 状态。
    """

    if not isinstance(value, dict):
        return {}
    template = str(value.get("planning_template") or fallback_template or "").strip()
    if template not in ALLOWED_TEMPLATES:
        template = fallback_template
    collector_categories = [
        str(item)
        for item in value.get("collector_categories", fallback_categories) or []
        if str(item) in ALLOWED_CATEGORIES
    ]
    enabled_skills = [
        str(item)
        for item in value.get("enabled_skills", []) or []
        if str(item) in ALLOWED_SKILLS
    ]
    slot_sequence = _clean_string_list(value.get("slot_sequence")) or fallback_slots
    movement_policy = str(value.get("movement_policy") or "").strip()
    if movement_policy not in ALLOWED_MOVEMENT_POLICIES:
        movement_policy = ""
    candidate_strategy = str(value.get("candidate_strategy") or "").strip()
    if candidate_strategy not in ALLOWED_CANDIDATE_STRATEGIES:
        candidate_strategy = ""
    return {
        "collector_categories": collector_categories[:8],
        "enabled_skills": enabled_skills,
        "planning_template": template,
        "slot_sequence": slot_sequence[:8],
        "required_slots": slot_sequence[:8],
        "movement_policy": movement_policy,
        "candidate_strategy": candidate_strategy,
        "reason": _clean_optional_string(value.get("reason")) or "",
    }


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
    """判断模型返回的偏好词是否可读。"""

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







from __future__ import annotations

import json
from typing import Any

from app.context.context_builder import ContextBuilder
from app.llm.output_schemas import IntentUnderstandingOutput, validate_llm_output
from app.llm.llm_client import call_chat_completion, extract_json_object
from app.llm.prompt_registry import load_prompt_template
from app.observability.trace_recorder import record_trace_event
from app.repositories.constants import (
    POI_ATTRACTION,
    POI_SHOPPING,
    POI_ACTIVITY,
    POI_RESTAURANT,
    POI_FITNESS,
    POI_ENTERTAINMENT,
    POI_BEAUTY,
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
ALLOWED_LOGICAL_CATEGORIES = {item.removeprefix("poi_") for item in ALLOWED_CATEGORIES}
ALLOWED_MISSING = {"people_or_scenario", "time_window", "preference", "location", "budget"}
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


def build_llm_understanding(
    query: str,
    user_profile: dict[str, Any] | None = None,
    *,
    conversation_context: dict[str, Any] | None = None,
    poi_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """调用 LLM 做结构化意图理解。

    这个 agent 只处理模型推理：prompt、LLM 调用、schema 校验、白名单规整。
    不能访问数据库，不能生成具体 POI，也不能改变后续召回和排序策略。
    """

    profile = user_profile or {}
    messages = [
        {
            "role": "system",
            "content": load_prompt_template(
                "intent_understanding",
                "你是本地生活规划系统的意图与约束理解器。"
                "你只做结构化理解，不推荐具体商家，不编造 POI、路线、价格或营业信息。"
                "必须只输出一个 JSON 对象，不要输出 Markdown。",
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
    """构造结构化抽取 prompt。

    用户画像和 Memory 只能作为软偏好，不得被模型复制成“本轮明确约束”。
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
1. intent_type 可选：capability、simple_qa、category_recommend、poi_search、full_trip_plan。
2. 如果本轮输入是“你是什么模型/你支持什么功能/怎么使用”，必须输出 simple_qa 或 capability。
3. 如果本轮输入是在修改上一轮方案，并且上下文存在历史方案，通常输出 full_trip_plan。
4. 多活动组合，例如“吃饭再看电影”“环球影城然后唱歌”，通常是 full_trip_plan。
5. 已说明同行对象或人数、日期/时间线索、活动偏好时，不要追问。
6. 预算和出发区域可以缺省，不要只因为缺预算或缺位置追问。
7. start_time 和 duration_hours 只有用户明确说了时间时才填写，不要自行补默认时间。
8. 历史画像只能影响后续排序，不得写入 preferences，除非本轮用户明确提到。
9. budget 必须做语义归一化：预算1k/1K/一千=1000，0.8万=8000。
10. 你必须直接规划 dynamic_slots，不要选择固定场景模板；slot 个数、顺序、类型和 max_duration_minutes 由用户时间、活动意图和节奏决定。
11. 如果用户明确给出总时长，dynamic_slots 的 max_duration_minutes 总和应尽量落在总时长内；如果用户没有明确给出总时长，根据规划内容在合理范围内自行给出每个 slot 的时长。
12. dynamic_slots.candidate_logical_categories 只能使用：restaurant、activity、attraction、shopping、fitness、entertainment、beauty。
13. category_tag_requirements 的标签只能从 POI 标签背景知识对应类别的 available_tags 中选择。
14. 用户明确偏好的标签写入 positive_logic_tags；明确排除的标签写入 negative_logic_tags。

target_categories 可选：
- poi_restaurant
- poi_activity
- poi_attraction
- poi_shopping
- poi_fitness
- poi_entertainment
- poi_beauty

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
  "planning_template": "",
  "required_slots": ["slot_1", "slot_2"],
  "dynamic_slots": [
    {{
      "slot_id": "slot_1",
      "slot_type": "attraction",
      "slot_name": "环球影城",
      "required": true,
      "candidate_logical_categories": ["attraction"],
      "max_duration_minutes": 180,
      "keywords": ["环球影城"],
      "reason": "用户明确想去环球影城"
    }},
    {{
      "slot_id": "slot_2",
      "slot_type": "entertainment",
      "slot_name": "唱歌",
      "required": true,
      "candidate_logical_categories": ["entertainment"],
      "max_duration_minutes": 120,
      "keywords": ["KTV", "唱歌"],
      "reason": "用户明确想唱歌"
    }}
  ],
  "must_pois": [
    {{"name": "北京环球度假区", "category": "poi_attraction", "must_include": true}}
  ],
  "preference_keywords": ["KTV"],
  "activity_intents": [
    {{"slot": "slot_2", "semantic_type": "ktv", "must_match": true, "keywords": ["KTV", "唱歌"]}}
  ],
  "category_tag_requirements": [
    {{"logical_category": "entertainment", "target_slot": "slot_2", "positive_logic_tags": ["KTV"], "negative_logic_tags": []}}
  ],
  "need_clarification": false,
  "missing_constraints": [],
  "clarify_question": ""
}}
"""


def _normalize_understanding(data: dict[str, Any]) -> dict[str, Any] | None:
    """校验并规整模型输出，避免不合法字段污染 PlanningState。"""

    intent_type = str(data.get("intent_type") or "").strip()
    if intent_type not in ALLOWED_INTENTS:
        return None

    categories = [
        str(item) for item in data.get("target_categories", []) if str(item) in ALLOWED_CATEGORIES
    ]
    preferences = _clean_string_list(data.get("preferences"))
    if not _has_readable_preference(preferences):
        preferences = _preferences_for_categories(categories)
    template = ""
    dynamic_slots = _clean_dynamic_slots(data.get("dynamic_slots"))
    required_slots = _clean_string_list(data.get("required_slots")) or [
        slot["slot_id"] for slot in dynamic_slots
    ]
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
        "dynamic_slots": dynamic_slots,
        "must_pois": _clean_must_pois(data.get("must_pois")),
        "preference_keywords": _clean_string_list(data.get("preference_keywords")),
        "activity_intents": _clean_activity_intents(data.get("activity_intents")),
        "category_tag_requirements": _clean_category_tag_requirements(
            data.get("category_tag_requirements")
        ),
        "dag_plan": _clean_dag_plan(
            data.get("dag_plan"), template, required_slots, categories, dynamic_slots
        ),
        "need_clarification": bool(data.get("need_clarification")),
        "missing_constraints": missing,
        "clarify_question": _clean_optional_string(data.get("clarify_question")) or "",
    }


def _clean_must_pois(value: Any) -> list[dict[str, Any]]:
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


def _clean_dynamic_slots(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        categories = [
            _clean_logical_category(category)
            for category in item.get("candidate_logical_categories", []) or []
        ]
        categories = [category for category in categories if category]
        slot_type = _clean_logical_category(item.get("slot_type"))
        if slot_type and slot_type not in categories:
            categories.insert(0, slot_type)
        if not categories:
            continue
        slot_id = _clean_optional_string(item.get("slot_id")) or f"slot_{index}"
        slot_id = _safe_slot_id(slot_id, index)
        if slot_id in seen:
            slot_id = f"{slot_id}_{index}"
        seen.add(slot_id)
        result.append({
            "slot_id": slot_id,
            "slot_type": slot_type or categories[0],
            "slot_name": _clean_optional_string(item.get("slot_name")) or slot_id,
            "required": bool(item.get("required", True)),
            "candidate_logical_categories": _dedupe(categories)[:4],
            "max_duration_minutes": _clean_int(item.get("max_duration_minutes")),
            "keywords": _clean_string_list(item.get("keywords"))[:8],
            "reason": _clean_optional_string(item.get("reason")) or "",
        })
    return result[:8]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _clean_logical_category(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("poi_"):
        text = text.removeprefix("poi_")
    return text if text in ALLOWED_LOGICAL_CATEGORIES else ""


def _safe_slot_id(value: str, index: int) -> str:
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in value.strip())
    return safe[:40] or f"slot_{index}"


def _clean_dag_plan(
    value: Any,
    fallback_template: str,
    fallback_slots: list[str],
    fallback_categories: list[str],
    fallback_dynamic_slots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        if fallback_dynamic_slots:
            return {
                "collector_categories": fallback_categories[:8],
                "planning_template": "",
                "slot_sequence": fallback_slots[:8],
                "required_slots": fallback_slots[:8],
                "dynamic_slots": list(fallback_dynamic_slots),
                "movement_policy": "",
                "candidate_strategy": "",
                "reason": "",
            }
        return {}
    template = ""
    collector_categories = [
        str(item)
        for item in value.get("collector_categories", fallback_categories) or []
        if str(item) in ALLOWED_CATEGORIES
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
        "planning_template": template,
        "slot_sequence": slot_sequence[:8],
        "required_slots": slot_sequence[:8],
        "dynamic_slots": (
            _clean_dynamic_slots(value.get("dynamic_slots")) or list(fallback_dynamic_slots or [])
        ),
        "movement_policy": movement_policy,
        "candidate_strategy": candidate_strategy,
        "reason": _clean_optional_string(value.get("reason")) or "",
    }


def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _has_readable_preference(preferences: list[str]) -> bool:
    return any(
        any("\u4e00" <= char <= "\u9fff" or (char.isascii() and char.isalnum()) for char in item)
        for item in preferences
    )


def _preferences_for_categories(categories: list[str]) -> list[str]:
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
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except TypeError, ValueError:
        return None


def _clean_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except TypeError, ValueError:
        return None

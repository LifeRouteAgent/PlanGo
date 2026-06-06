from __future__ import annotations

from typing import Any

from app.context.context_builder import ContextBuilder
from app.llm.llm_client import call_chat_completion, extract_json_object
from app.llm.output_schemas import (
    MemoryExtractionOutput,
    RevisionConstraintOutput,
    validate_llm_output,
)
from app.llm.prompt_registry import load_prompt_template
from app.observability.trace_recorder import record_trace_event


def extract_memory_updates(query: str, *, user_profile: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """用 LLM 判断用户输入是否应该沉淀为长期偏好。

    规则只能判断显式关键词，无法区分“今天太热”这种本轮临时约束和长期偏好。
    因此 Memory 写入优先走 LLM 结构化抽取，失败时调用方再走保守规则兜底。
    """

    context_snapshot = ContextBuilder().build_for(
        "memory_extractor",
        _state_for_context(query=query, user_profile=user_profile or {}),
    )
    prompt = f"""
你是本地生活 Agent 的长期记忆抽取器。请判断用户本轮输入是否应该写入长期画像。
只输出 JSON，不要 Markdown，不要编造用户没说过的信息。

用户输入：
{query}

当前画像：
{user_profile or {}}

结构化上下文快照：
{context_snapshot}

判断规则：
1. 长期画像只写稳定偏好，例如长期偏室内、长期低预算、常去区域、长期不喜欢某类。
2. “今天太热/今天下雨/这次不要室外”通常是 temporary，不要强写长期画像；可以写入事件记忆。
3. “我以后都不想/我一直不喜欢/我通常/我经常/我偏好”更可能是 long_term。
4. 不要写 API key、手机号、完整地址等敏感信息。

输出格式：
{{
  "should_update_profile": false,
  "scope": "temporary",
  "confidence": 0.0,
  "profile_updates": {{
    "indoor_preference": null,
    "budget_level": null,
    "preferred_areas": [],
    "favorite_categories": [],
    "disliked_keywords": []
  }},
  "memory_text": "一句话摘要",
  "tags": []
}}
"""
    return _call_json_extractor(
        "llm.memory_extractor",
        prompt,
        max_tokens=900,
        schema=MemoryExtractionOutput,
    )


def extract_revision_constraints(
    query: str,
    *,
    previous_constraints: dict[str, Any] | None = None,
    user_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """用 LLM 把中途修改需求转成结构化约束。"""

    context_snapshot = ContextBuilder().build_for(
        "revision_parser",
        _state_for_context(
            query=query,
            user_profile=user_profile or {},
            constraints=previous_constraints or {},
        ),
    )
    prompt = f"""
你是本地生活规划 Agent 的需求修正解析器。请把用户中途修改需求转成结构化约束。
只输出 JSON，不要 Markdown。不要重新规划，不要推荐具体 POI。

用户修改需求：
{query}

上一版约束：
{previous_constraints or {}}

用户画像（只能作为软参考）：
{user_profile or {}}

结构化上下文快照：
{context_snapshot}

输出格式：
{{
  "revision_type": "global_constraint",
  "indoor_preferred": null,
  "avoid_tags": [],
  "excluded_keywords": [],
  "budget": null,
  "budget_strategy": null,
  "price_preference": null,
  "max_route_minutes": null,
  "movement_policy": null,
  "preferred_categories": [],
  "activity_intents": [
    {{"slot": "entertainment", "semantic_type": "ktv", "must_match": true, "keywords": ["KTV"]}}
  ],
  "reason": "一句话说明"
}}

字段约定：
- indoor_preferred 只有用户明确要求室内、不要室外、天气影响时才填 true。
- excluded_keywords 只放用户明确不要的内容。
- budget 只在用户明确更正预算时填写整数元，例如 1k/一千 输出 1000。
- max_route_minutes 只有用户明确说更近、少走路、别太远时才填。
- activity_intents 用来表达唱歌=ktv、麻将=chess_cards、电影=cinema 等语义垂类。
"""
    return _call_json_extractor(
        "llm.revision_parser",
        prompt,
        max_tokens=1000,
        schema=RevisionConstraintOutput,
    )


def _state_for_context(
    *,
    query: str,
    user_profile: dict[str, Any],
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为语义抽取器构造最小 PlanState，避免直接拼完整会话历史。"""

    return {
        "user_query": query,
        "user_profile": user_profile,
        "constraints": constraints or {},
        "dag_plan": {},
        "candidate_pois": {},
        "recommended_pois": {},
        "ranked_plans": [],
        "errors": [],
        "logs": [],
    }


def _call_json_extractor(
    tool_name: str,
    prompt: str,
    *,
    max_tokens: int,
    schema: type[Any] | None = None,
) -> dict[str, Any] | None:
    """统一调用 LLM 并记录结构化抽取 trace。"""

    raw = call_chat_completion(
        [
            {
                "role": "system",
                "content": load_prompt_template(
                    _prompt_name_for_tool(tool_name),
                    "你是结构化信息抽取器。必须只输出一个 JSON 对象。",
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        timeout_seconds=30,
        max_completion_tokens=max_tokens,
        prompt_name=tool_name.removeprefix("llm.").replace("_parser", "_parser"),
        schema_name=schema.__name__ if schema else None,
    )
    parsed = extract_json_object(raw)
    record_trace_event(
        "llm_semantic_extractor",
        {
            "tool": tool_name,
            "success": bool(parsed),
            "raw_preview": raw[:600] if raw else "",
            "parsed": parsed or {},
        },
    )
    if not isinstance(parsed, dict):
        return None
    if schema is None:
        return parsed
    validation = validate_llm_output(schema, parsed, source=tool_name)
    return validation.data if validation.ok else None


def _prompt_name_for_tool(tool_name: str) -> str:
    if "memory" in tool_name:
        return "memory_extractor"
    if "followup" in tool_name:
        return "followup_context"
    return "revision_parser"


from __future__ import annotations

import json
from typing import Any

from app.llm.output_schemas import ResponseGenerationOutput, validate_llm_output
from app.llm.llm_client import call_chat_completion, extract_json_object
from app.llm.prompt_registry import load_prompt_template
from app.observability.trace_recorder import TraceRecorder


def generate_response_package(payload: dict[str, Any]) -> dict[str, Any] | None:
    """用 LLM 生成用户可见展示文案。

    只发送脱敏后的方案摘要给当前配置的 LLM provider。LLM 只能生成展示字段，
    不能新增/修改 POI、路线、排序、预算和可用性事实。
    """

    if payload.get("response_type") not in {"plan_cards", "plan_adjustment_result", "poi_list"}:
        return None
    compact_payload = compact_payload_for_llm(payload)
    messages = [
        {
            "role": "system",
            "content": load_prompt_template(
                "response_generation_package",
                "你是本地生活规划系统的响应包生成器。只能基于输入 JSON 生成展示文案。",
            ),
        },
        {
            "role": "user",
            "content": json.dumps(compact_payload, ensure_ascii=False, default=str),
        },
    ]
    raw = call_chat_completion(
        messages,
        temperature=0.3,
        timeout_seconds=30,
        max_completion_tokens=2048,
        prompt_name="response_generation_package",
        schema_name="ResponseGenerationOutput",
    )
    parsed = extract_json_object(raw)
    validation = (
        validate_llm_output(ResponseGenerationOutput, parsed, source="response_generation_package")
        if isinstance(parsed, dict)
        else None
    )
    if not validation or not validation.ok:
        TraceRecorder.record(
            "response_generation_skipped",
            {"reason": "schema_invalid_or_llm_unavailable", "raw_preview": str(raw or "")[:600]},
        )
        return None
    return validation.data


def apply_response_generation(
    payload: dict[str, Any], generation: dict[str, Any] | None
) -> dict[str, Any]:
    """把 LLM 展示增强合并回 payload。

    只允许覆盖展示字段，不允许改变 items、route_segments、timeline 等事实字段。
    """

    if not generation:
        return payload
    result = dict(payload)
    plans = [dict(plan) for plan in result.get("plans", []) if isinstance(plan, dict)]
    enrichments = {
        str(plan.get("id") or ""): plan
        for plan in generation.get("plans", [])
        if isinstance(plan, dict) and plan.get("id")
    }
    for plan in plans:
        enrichment = enrichments.get(str(plan.get("id") or plan.get("plan_id") or ""))
        if not enrichment:
            continue
        title = str(enrichment.get("title") or "").strip()
        if title:
            plan["title"] = title[:18]
        _apply_short_list(plan, enrichment, "highlight_tags", limit=4, max_chars=6)
        _apply_short_list(plan, enrichment, "tags", limit=4, max_chars=6)
        _apply_short_list(plan, enrichment, "pros", limit=3, max_chars=15)
        _apply_short_list(plan, enrichment, "cons", limit=3, max_chars=15)
        if enrichment.get("recommendation_reason"):
            plan["recommendation_reason"] = str(enrichment["recommendation_reason"]).strip()[:80]
        _apply_item_generation(plan, enrichment)
    result["plans"] = plans
    if plans:
        selected_id = str((result.get("selected_plan") or {}).get("id") or "")
        result["selected_plan"] = next(
            (plan for plan in plans if str(plan.get("id")) == selected_id), plans[0]
        )
    if generation.get("response_text"):
        result["_llm_final_text"] = str(generation["response_text"]).strip()
    return result


def compact_payload_for_llm(payload: dict[str, Any]) -> dict[str, Any]:
    """构造给 LLM 的最小事实包。

    刻意排除经纬度、路线 polyline、debug、raw_extra、SQL、用户原始输入和 Memory 原文。
    """

    return {
        "response_type": payload.get("response_type"),
        "summary": payload.get("summary"),
        "warnings": list(payload.get("warnings", []))[:5],
        "plans": [
            _compact_plan(plan) for plan in payload.get("plans", [])[:3] if isinstance(plan, dict)
        ],
        "poi_list": [
            _compact_item(item)
            for item in payload.get("poi_list", [])[:8]
            if isinstance(item, dict)
        ],
    }


def _compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": plan.get("id") or plan.get("plan_id"),
        "title": plan.get("title"),
        "tags": list(plan.get("tags", []))[:4],
        "pros": list(plan.get("pros", []))[:3],
        "cons": list(plan.get("cons", []))[:3],
        "route_text": plan.get("route_text"),
        "budget_text": plan.get("budget_text"),
        "route_minutes": plan.get("route_minutes"),
        "estimated_budget": plan.get("estimated_budget"),
        "warnings": list(plan.get("warnings", []))[:5],
        "items": [
            _compact_item(item) for item in plan.get("items", [])[:5] if isinstance(item, dict)
        ],
    }


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id") or item.get("poi_id"),
        "name": item.get("name"),
        "display_category": item.get("display_category"),
        "subcategory": item.get("subcategory"),
        "rating": item.get("rating"),
        "avg_price": item.get("avg_price"),
        "tags": list(item.get("tags", []))[:6],
        "reason": item.get("reason") or item.get("recommendation_reason"),
    }


def _apply_short_list(
    plan: dict[str, Any],
    enrichment: dict[str, Any],
    key: str,
    *,
    limit: int,
    max_chars: int,
) -> None:
    values = enrichment.get(key)
    if not isinstance(values, list) or not values:
        return
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in result:
            continue
        result.append(text[:max_chars])
        if len(result) >= limit:
            break
    if result:
        plan[key] = result


def _apply_item_generation(plan: dict[str, Any], enrichment: dict[str, Any]) -> None:
    item_enrichments = {
        str(item.get("id") or ""): item
        for item in enrichment.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    items = [dict(item) for item in plan.get("items", []) if isinstance(item, dict)]
    for item in items:
        item_enrichment = item_enrichments.get(str(item.get("id") or ""))
        if item_enrichment and item_enrichment.get("recommendation_reason"):
            item["recommendation_reason"] = str(item_enrichment["recommendation_reason"]).strip()[
                :80
            ]
    plan["items"] = items

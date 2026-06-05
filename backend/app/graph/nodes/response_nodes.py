from __future__ import annotations

from typing import Any

from app.graph.nodes.common import append_trace, ensure_state
from app.graph.services import assemble_state_response
from app.graph.state import PlanningState


def response_assembler_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    response = state.response.model_copy(deep=True)
    if not response.response_payload:
        response.response_payload = assemble_state_response(state)
        response.response_type = str(response.response_payload.get("response_type") or "plan_cards")
    return {
        "response": response,
        "debug": append_trace(state, "response_assembler", "assembled structured response payload"),
    }


def response_generator_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    response = state.response.model_copy(deep=True)
    payload = response.response_payload or {}
    payload = _sanitize_display_payload(payload)
    response.response_payload = payload
    plans = [plan for plan in payload.get("plans", []) if isinstance(plan, dict)]
    if plans:
        lines = ["我按你的需求筛出这些方案："]
        for index, plan in enumerate(plans[:3], start=1):
            pros = "、".join(plan.get("pros", [])[:2]) or "匹配需求"
            cons = "、".join(plan.get("cons", [])[:1]) or "需确认状态"
            lines.append(f"{index}. {plan.get('title', '方案')}：{pros}；注意 {cons}。")
        if payload.get("warnings"):
            lines.append("补充：" + "；".join(str(item) for item in payload["warnings"][:2]))
        response.final_text = "\n".join(lines)
    elif payload.get("poi_list"):
        response.final_text = "\n".join(
            ["为你推荐这些地点："]
            + [
                f"{index}. {item['name']}｜评分 {item.get('rating') or '未知'}"
                for index, item in enumerate(payload["poi_list"][:8], 1)
            ]
        )
    else:
        response.final_text = str(payload.get("summary") or "暂时没有找到满足条件的方案。")
    return {
        "response": response,
        "debug": append_trace(state, "response_generator", "generated final text from response payload"),
    }


def _sanitize_display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    plans = [_sanitize_plan(plan, index) for index, plan in enumerate(result.get("plans", []), start=1) if isinstance(plan, dict)]
    result["plans"] = plans
    if plans:
        selected_id = str((result.get("selected_plan") or {}).get("id") or (result.get("selected_plan") or {}).get("plan_id") or "")
        result["selected_plan"] = next((plan for plan in plans if str(plan.get("id") or plan.get("plan_id")) == selected_id), plans[0])
    if isinstance(result.get("poi_list"), list):
        result["poi_list"] = [_sanitize_item(item) for item in result["poi_list"] if isinstance(item, dict)]
    return result


def _sanitize_plan(plan: dict[str, Any], index: int) -> dict[str, Any]:
    clean = dict(plan)
    clean["items"] = [_sanitize_item(item) for item in clean.get("items", []) if isinstance(item, dict)]
    clean["title"] = _display_title(clean, index)
    clean["highlight_tags"] = _short_list(clean.get("highlight_tags") or clean.get("tags"), _fallback_highlights(clean), 4, 6)
    clean["tags"] = clean["highlight_tags"]
    clean["pros"] = _short_list(clean.get("pros"), _fallback_pros(clean), 3, 15)
    clean["cons"] = _short_list(clean.get("cons"), _fallback_cons(clean), 3, 15)
    return clean


def _sanitize_item(item: dict[str, Any]) -> dict[str, Any]:
    clean = dict(item)
    clean["tags"] = _short_list(clean.get("tags"), [clean.get("display_category") or _category_label(clean.get("logical_category"))], 6, 15)
    if not clean.get("display_category"):
        clean["display_category"] = _category_label(clean.get("logical_category"))
    return clean


def _display_title(plan: dict[str, Any], index: int) -> str:
    title = str(plan.get("title") or "").strip()
    if title and " + " not in title and len(title) <= 16 and not _looks_like_raw_text(title):
        return title[:18]
    labels = []
    for item in plan.get("items", []):
        label = str(item.get("display_category") or _category_label(item.get("logical_category")))
        if label and label not in labels:
            labels.append(label)
    if labels:
        return f"{'＋'.join(labels[:2])}轻松线"[:18]
    return f"方案{index}"


def _fallback_highlights(plan: dict[str, Any]) -> list[str]:
    labels = [str(item.get("display_category") or _category_label(item.get("logical_category"))) for item in plan.get("items", [])]
    return [*labels, "路线清晰", "节奏轻松"]


def _fallback_pros(plan: dict[str, Any]) -> list[str]:
    route_minutes = int(plan.get("route_minutes") or 0)
    values = ["地点匹配", "路线清晰"]
    if route_minutes:
        values.append(f"交通{route_minutes}分钟")
    return values


def _fallback_cons(plan: dict[str, Any]) -> list[str]:
    warnings = [str(item).split(":", 1)[0] for item in plan.get("warnings", []) if item]
    return warnings[:2] or ["出发前确认"]


def _short_list(primary: Any, fallback: Any, limit: int, max_chars: int) -> list[str]:
    values = primary if isinstance(primary, list) and primary else fallback
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or _looks_like_raw_text(text):
            continue
        if text.lower() == "ktv":
            text = "KTV"
        text = text[:max_chars]
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    if not result and values is not fallback:
        return _short_list(fallback, [], limit, max_chars)
    return result


def _looks_like_raw_text(text: str) -> bool:
    lowered = text.lower()
    return (
        any(mark in text for mark in ("{", "}", "[", "]"))
        or "," in text
        or "，" in text
        or "sub_category_id" in lowered
        or "leaf_category_id" in lowered
        or lowered in {"activity", "attraction", "restaurant", "shopping", "entertainment", "cinema", "mixed"}
    )


def _category_label(category: Any) -> str:
    return {
        "restaurant": "餐饮",
        "activity": "活动",
        "attraction": "景点",
        "shopping": "购物",
        "entertainment": "娱乐",
        "fitness": "运动",
        "beauty": "放松",
    }.get(str(category or "").replace("poi_", ""), "本地生活")


def simple_response_generator_node(value: PlanningState | dict[str, Any]) -> dict[str, Any]:
    state = ensure_state(value)
    response = state.response.model_copy(deep=True)
    response.response_type = "simple_text"
    response.response_payload = {"response_type": "simple_text"}
    response.final_text = "我是 PlanGo 本地生活规划助手，可以帮你推荐地点并生成可执行行程。"
    return {
        "response": response,
        "debug": append_trace(state, "simple_response_generator", "generated simple response"),
    }

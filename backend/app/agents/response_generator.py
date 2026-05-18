from __future__ import annotations

import json

from app.agents.issue_utils import normalize_issues
from app.services.llm_service import call_chat_completion
from app.state.plan_state import PlanState, PlanStatePatch


def response_generator_node(state: PlanState) -> PlanStatePatch:
    """根据意图类型生成最终响应。

    同一个 Response Generator 同时服务完整行程、分类推荐和简单问答，
    这样前端只需要展示统一的 `response_text`。
    """

    if state.get("answer_mode") == "capability":
        llm_text = _llm_response_text(state, _capability_text())
        return {
            "response_text": llm_text or _capability_text(),
            "logs": [
                "Response Generator: generated capability answer"
                + (" with LLM" if llm_text else " with template fallback")
            ],
        }
    if state.get("answer_mode") == "simple_qa":
        fallback = _simple_answer_text(state["user_query"])
        llm_text = _llm_response_text(state, fallback)
        return {
            "response_text": llm_text or fallback,
            "logs": [
                "Response Generator: generated simple answer"
                + (" with LLM" if llm_text else " with template fallback")
            ],
        }
    if state.get("answer_mode") == "clarification" or state.get("need_clarification"):
        fallback = (
            state.get("clarify_question")
            or "还需要补充同行人数、可用时间和偏好后，才能生成可执行方案。"
        )
        llm_text = _llm_response_text(state, fallback)
        return {
            "response_text": llm_text or fallback,
            "logs": [
                "Response Generator: generated clarification question"
                + (" with LLM" if llm_text else " with template fallback")
            ],
        }
    if state.get("answer_mode") in {"category_recommend", "poi_search"}:
        return _category_recommendation_response(state)

    selected = state.get("selected_plan") or {}
    if not selected:
        text = "暂时没有生成可执行方案，请调整时间、预算或偏好后重试。"
    else:
        names = " -> ".join(item["name"] for item in selected.get("items", []))
        issues = normalize_issues(selected.get("issues", []))
        warning_codes = "、".join(sorted({issue["code"] for issue in issues})) or "无"
        timeline_summary = _timeline_summary(selected)
        route_summary = _route_summary(selected)
        text = (
            f"{selected.get('title', '本地生活方案')}\n"
            f"路线：{names}\n"
            f"方案评分：{selected.get('plan_score', '待计算')}\n"
            f"预计时长：{selected.get('total_duration_minutes')} 分钟\n"
            f"交通：{route_summary}\n"
            f"预计预算：{selected.get('estimated_budget')} 元\n"
            f"校验提醒：{warning_codes}\n"
            f"{timeline_summary}\n"
            "当前为模拟方案，等待用户确认后可进入执行节点。"
        )
    llm_text = _llm_response_text(state, text)
    return {
        "response_text": llm_text or text,
        "logs": [
            "Response Generator: generated response text"
            + (" with LLM" if llm_text else " with template fallback")
        ],
    }


def response_route(state: PlanState) -> str:
    """响应生成后的条件边。

    只有完整行程规划才进入用户确认和执行节点；推荐和问答到这里就结束。
    """

    if state.get("need_clarification") or state.get("answer_mode") == "clarification":
        return "end"
    return "execute" if state.get("intent_type") == "full_trip_plan" else "end"


def _category_recommendation_response(state: PlanState) -> PlanStatePatch:
    selected = state.get("selected_plan") or {}
    items = selected.get("items", [])
    if not items:
        text = "暂时没有找到匹配的本地生活候选，请换一个类别或放宽条件。"
    else:
        lines = ["为你推荐这些本地生活地点："]
        for index, item in enumerate(items[:8], start=1):
            tags = "、".join(item.get("tags", [])[:3]) or item.get("subcategory", "本地生活")
            score = item.get("score", item.get("rating", 0))
            lines.append(
                f"{index}. {item['name']}｜{item.get('address', '地址待补充')}｜评分 {score}｜{tags}"
            )
        text = "\n".join(lines)
    llm_text = _llm_response_text(state, text)
    return {
        "response_text": llm_text or text,
        "logs": [
            "Response Generator: generated category recommendation text"
            + (" with LLM" if llm_text else " with template fallback")
        ],
    }


def _llm_response_text(state: PlanState, fallback_text: str) -> str | None:
    """让大模型把结构化 PlanState 改写成自然语言响应。

    这里把模型限定在“表达层”：只能使用 PlanState 里已经存在的方案、地点、
    路线、预算和错误信息，不能新增商家、不能新增路线、不能宣称真实预约成功。
    如果模型不可用或返回空文本，则使用模板化 fallback。
    """

    response_context = {
        "user_query": state.get("user_query"),
        "intent_type": state.get("intent_type"),
        "answer_mode": state.get("answer_mode"),
        "need_clarification": state.get("need_clarification"),
        "clarify_question": state.get("clarify_question"),
        "constraints": {
            key: value
            for key, value in state.get("constraints", {}).items()
            if key != "llm_understanding"
        },
        "llm_understanding": state.get("constraints", {}).get("llm_understanding"),
        "selected_plan": state.get("selected_plan"),
        "errors": state.get("errors"),
        "fallback_text": fallback_text,
    }
    raw = call_chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是本地生活规划系统的响应生成器。"
                    "只能基于用户提供的 PlanState 生成中文回复。"
                    "禁止编造 PlanState 中不存在的 POI、路线、营业状态、价格、预约结果。"
                    "如果 PlanState 信息不足，就基于 fallback_text 简洁表达。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(response_context, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.2,
    )
    if not raw:
        return None
    text = raw.strip()
    return text or None


def _timeline_summary(selected: dict) -> str:
    """把时间线压缩成文本摘要，方便 API 调用方不解析 JSON 也能读懂方案。"""

    timeline = selected.get("timeline", [])
    if not timeline:
        return "时间线：待生成"
    parts = [
        f"{item.get('start_time')}-{item.get('end_time', '待定')} {item.get('title')}"
        for item in timeline[:4]
    ]
    return "时间线：" + "；".join(parts)


def _route_summary(selected: dict) -> str:
    """生成路线交通摘要。"""

    route_minutes = selected.get("route_minutes", 0)
    distance = selected.get("total_distance_km", 0)
    modes = [
        segment.get("transport_mode")
        for segment in selected.get("route_segments", [])
        if segment.get("transport_mode")
    ]
    mode_text = "、".join(dict.fromkeys(modes)) if modes else "无需换乘"
    return f"{route_minutes} 分钟，约 {distance} km，方式：{mode_text}"


def _capability_text() -> str:
    return (
        "我可以帮你做三类事情：\n"
        "1. 完整行程规划：根据人数、时间、预算和偏好安排活动、餐厅和路线。\n"
        "2. 分类推荐：只推荐餐厅、电影、按摩、健身、景点、购物等某一类地点。\n"
        "3. 简单问答：说明系统能力、数据源状态和使用方式。\n"
        "如果你想要完整规划，可以说：周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元。"
    )


def _simple_answer_text(query: str) -> str:
    return (
        "我理解这是一个简单询问，不需要启动完整行程规划。\n"
        f"你的问题是：{query}\n"
        "你可以继续问我支持什么功能，或者直接说想推荐哪一类本地生活地点。"
    )

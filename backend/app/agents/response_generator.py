from __future__ import annotations

import json
from typing import Any

from app.agents.issue_utils import normalize_issues
from app.services.llm_service import call_chat_completion, extract_json_object
from app.state.plan_state import PlanState, PlanStatePatch


def response_generator_node(state: PlanState) -> PlanStatePatch:
    """根据意图类型生成最终响应。

    这个节点同时承担两层职责：
    1. 生成 `response_text`，给普通文本区域和流式输出使用。
    2. 给 `ranked_plans` / `selected_plan` 补充展示字段，例如方案推荐理由、优缺点、
       每个 POI 的一句推荐理由和可选调整项。

    注意：LLM 在这里只做表达层增强，不允许新增 POI、修改路线、修改价格或声称真实预约成功。
    """

    if state.get("answer_mode") == "capability":
        fallback = _capability_text()
        llm_text = _llm_response_text(state, fallback)
        return {
            "response_text": llm_text or fallback,
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

    ranked_plans = _enrich_ranked_plans_for_presentation(state)
    selected = ranked_plans[0] if ranked_plans else state.get("selected_plan") or {}
    fallback_text = _full_plan_text(selected, ranked_plans)
    llm_text = _llm_response_text(state, fallback_text, ranked_plans=ranked_plans, selected_plan=selected)
    return {
        "response_text": llm_text or fallback_text,
        "ranked_plans": ranked_plans or state.get("ranked_plans", []),
        "selected_plan": selected,
        "logs": [
            "Response Generator: generated response text"
            + (" with LLM" if llm_text else " with template fallback")
        ],
    }


def response_route(state: PlanState) -> str:
    """响应生成后的条件边。

    只有完整行程规划才进入用户确认和模拟执行；分类推荐、简单问答、澄清问题都在这里结束。
    """

    if state.get("need_clarification") or state.get("answer_mode") == "clarification":
        return "end"
    return "execute" if state.get("intent_type") == "full_trip_plan" else "end"


def _category_recommendation_response(state: PlanState) -> PlanStatePatch:
    """生成单类推荐响应。

    单类推荐没有完整路线时间线，但仍然会给 POI 补一句推荐理由和可选调整项，
    方便前端使用统一的卡片结构展示。
    """

    ranked_plans = _enrich_ranked_plans_for_presentation(state)
    selected = ranked_plans[0] if ranked_plans else state.get("selected_plan") or {}
    items = selected.get("items", [])

    if not items:
        text = "暂时没有找到匹配的本地生活候选，请换一个类别或放宽条件。"
    else:
        lines = ["为你推荐这些本地生活地点："]
        for index, item in enumerate(items[:8], start=1):
            tags = "、".join(item.get("tags", [])[:3]) or item.get("subcategory", "本地生活")
            score = item.get("score", item.get("rating", 0))
            reason = item.get("recommendation_reason") or item.get("reason", "匹配当前偏好")
            lines.append(f"{index}. {item['name']}｜评分 {score}｜{tags}｜{reason}")
        text = "\n".join(lines)

    llm_text = _llm_response_text(state, text, ranked_plans=ranked_plans, selected_plan=selected)
    return {
        "response_text": llm_text or text,
        "ranked_plans": ranked_plans or state.get("ranked_plans", []),
        "selected_plan": selected,
        "logs": [
            "Response Generator: generated category recommendation text"
            + (" with LLM" if llm_text else " with template fallback")
        ],
    }


def _enrich_ranked_plans_for_presentation(state: PlanState) -> list[dict[str, Any]]:
    """为前端展示补充结构化解释字段。

    返回最多 3 个方案。若 LLM 不可用，使用 deterministic fallback，保证前端字段稳定。
    """

    ranked_plans = [dict(plan) for plan in state.get("ranked_plans", [])[:3]]
    if not ranked_plans:
        return []

    fallback = [_fallback_enrich_plan(plan, index) for index, plan in enumerate(ranked_plans, start=1)]
    llm_plans = _llm_plan_enrichment(state, fallback)
    if not llm_plans:
        return fallback

    llm_by_id = {
        str(plan.get("id", index)): plan
        for index, plan in enumerate(llm_plans, start=1)
        if isinstance(plan, dict)
    }
    merged: list[dict[str, Any]] = []
    for index, plan in enumerate(fallback, start=1):
        merged.append(_merge_plan_enrichment(plan, llm_by_id.get(str(plan.get("id", index)), {}), index))
    return merged


def _llm_plan_enrichment(state: PlanState, fallback_plans: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """用 LLM 生成方案优缺点和 POI 可选调整项。

    输入只包含已有方案和已有 POI，输出必须引用相同 id。后续合并时也只按 id 合并文案字段，
    不接受 LLM 新增的地点、路线或预算。
    """

    compact_plans = []
    for plan in fallback_plans:
        compact_plans.append(
            {
                "id": plan.get("id"),
                "title": plan.get("title"),
                "plan_score": plan.get("plan_score"),
                "total_duration_minutes": plan.get("total_duration_minutes"),
                "route_minutes": plan.get("route_minutes"),
                "estimated_budget": plan.get("estimated_budget"),
                "items": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "category": item.get("category"),
                        "subcategory": item.get("subcategory"),
                        "rating": item.get("rating"),
                        "reason": item.get("reason"),
                        "tags": item.get("tags", [])[:5],
                    }
                    for item in plan.get("items", [])
                ],
                "issues": plan.get("issues", []),
            }
        )

    raw = call_chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是本地生活规划方案展示文案生成器。"
                    "只能基于输入 JSON 解释已有方案，禁止新增地点、禁止修改路线、禁止修改预算。"
                    "必须只输出 JSON 对象，不要 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_query": state.get("user_query"),
                        "constraints": {
                            key: value
                            for key, value in state.get("constraints", {}).items()
                            if key != "llm_understanding"
                        },
                        "plans": compact_plans,
                        "required_schema": {
                            "plans": [
                                {
                                    "id": "必须等于输入 plan id",
                                    "recommendation_reason": "一句话说明这个方案适合谁",
                                    "pros": ["优点1", "优点2"],
                                    "cons": ["缺点1", "缺点2"],
                                    "plan_actions": [
                                        {
                                            "id": "必须是 execute_plan、share_pdf 或自定义英文 id",
                                            "label": "按钮文案",
                                            "type": "execute | export | refine",
                                            "prompt": "点击后代表的调整意图",
                                        }
                                    ],
                                    "items": [
                                        {
                                            "id": "必须等于输入 poi id",
                                            "recommendation_reason": "每个地点一行简短推荐理由",
                                            "option_prompts": ["再近一点", "换成室内", "不要火锅"],
                                        }
                                    ],
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ],
        temperature=0.35,
        max_completion_tokens=1800,
    )
    parsed = extract_json_object(raw)
    plans = parsed.get("plans") if parsed else None
    return plans if isinstance(plans, list) else None


def _fallback_enrich_plan(plan: dict[str, Any], index: int) -> dict[str, Any]:
    """LLM 不可用时的方案展示字段兜底。"""

    items = [_fallback_enrich_item(item) for item in plan.get("items", [])]
    issue_codes = [
        str(issue.get("code"))
        for issue in normalize_issues(plan.get("issues", []))
        if issue.get("code")
    ]
    route_minutes = int(plan.get("route_minutes", 0) or 0)
    total_duration = int(plan.get("total_duration_minutes", 0) or 0)
    budget = int(plan.get("estimated_budget", 0) or 0)
    return {
        **plan,
        "items": items,
        "recommendation_reason": f"方案 {index} 兼顾偏好、路程和时间窗口，适合直接作为可执行备选。",
        "pros": [
            f"总时长约 {total_duration} 分钟，方便判断是否塞得进时间窗口。",
            f"交通约 {route_minutes} 分钟，动线成本可量化。",
        ],
        "cons": [
            f"预算估算约 {budget} 元，实际价格仍建议到店前确认。",
            "热门地点可能需要排队或预约。" if issue_codes else "营业和排队信息仍建议出发前复核。",
        ],
        "plan_actions": _default_plan_actions(plan),
    }


def _fallback_enrich_item(item: dict[str, Any]) -> dict[str, Any]:
    """LLM 不可用时的 POI 展示字段兜底。"""

    category_options = {
        "poi_restaurant": ["不要火锅", "换成人均更低", "找评分更高"],
        "poi_entertainment": ["再近一点", "换成室内", "换成安静一点"],
        "poi_activity": ["换成室内", "缩短停留时间", "换成亲子友好"],
        "poi_attraction": ["换成室内", "少走路", "换成免费地点"],
        "poi_shopping": ["再近一点", "换成停车方便", "换成人少一点"],
        "poi_fitness": ["降低强度", "换成室内", "改成团体运动"],
        "poi_beauty": ["缩短服务时间", "换成更便宜", "改成足疗按摩"],
    }
    tags = "、".join(item.get("tags", [])[:2])
    reason = item.get("reason") or (
        f"{item.get('subcategory', '本地生活地点')}匹配当前偏好"
        + (f"，标签包含 {tags}" if tags else "")
    )
    return {
        **item,
        "recommendation_reason": str(reason).split("。")[0][:48],
        "option_prompts": category_options.get(str(item.get("category")), ["再近一点", "换成室内", "降低预算"]),
    }


def _merge_plan_enrichment(plan: dict[str, Any], extra: dict[str, Any], index: int) -> dict[str, Any]:
    """把 LLM 文案安全合并回原方案。"""

    merged = dict(plan)
    reason = extra.get("recommendation_reason")
    if isinstance(reason, str) and reason.strip():
        merged["recommendation_reason"] = reason.strip()

    pros = extra.get("pros")
    if isinstance(pros, list) and pros:
        merged["pros"] = [str(item).strip() for item in pros[:3] if str(item).strip()]

    cons = extra.get("cons")
    if isinstance(cons, list) and cons:
        merged["cons"] = [str(item).strip() for item in cons[:3] if str(item).strip()]

    merged["plan_actions"] = _merge_plan_actions(plan, extra.get("plan_actions"))

    extra_items = (
        {
            str(item.get("id")): item
            for item in extra.get("items", [])
            if isinstance(item, dict) and item.get("id")
        }
        if isinstance(extra.get("items"), list)
        else {}
    )
    merged["items"] = [
        _merge_item_enrichment(item, extra_items.get(str(item.get("id")), {}))
        for item in merged.get("items", [])
    ]
    merged.setdefault("recommendation_reason", f"方案 {index} 是当前排序靠前的可执行备选。")
    merged.setdefault("pros", ["偏好匹配度较高。"])
    merged.setdefault("cons", ["仍需出发前确认营业和排队情况。"])
    return merged


def _default_plan_actions(plan: dict[str, Any]) -> list[dict[str, str]]:
    """生成方案级默认操作，确保核心按钮永远存在。

    前两个按钮是产品固定能力：执行方案、分享/导出 PDF。
    后两个是可被 LLM 覆盖的调整建议；LLM 不可用时使用确定性兜底。
    """

    return [
        {
            "id": "execute_plan",
            "label": "执行此方案",
            "type": "execute",
            "prompt": "按当前方案模拟预约、购票和打车。",
        },
        {
            "id": "share_pdf",
            "label": "分享方案（导出 PDF）",
            "type": "export",
            "prompt": "把当前方案导出成可分享 PDF。",
        },
        {
            "id": "cheaper",
            "label": "换个更省钱的",
            "type": "refine",
            "prompt": "在保留主要偏好的前提下，降低预算和人均消费。",
        },
        {
            "id": "closer",
            "label": "换个更近的",
            "type": "refine",
            "prompt": "优先选择距离更近、交通时间更短的地点。",
        },
    ]


def _merge_plan_actions(plan: dict[str, Any], llm_actions: Any) -> list[dict[str, str]]:
    """合并 LLM 方案操作，并强制保留执行和导出两个核心按钮。"""

    fixed = _default_plan_actions(plan)[:2]
    fixed_ids = {action["id"] for action in fixed}
    dynamic: list[dict[str, str]] = []
    if isinstance(llm_actions, list):
        for action in llm_actions:
            if not isinstance(action, dict):
                continue
            action_id = str(action.get("id") or "").strip()
            label = str(action.get("label") or "").strip()
            action_type = str(action.get("type") or "refine").strip()
            prompt = str(action.get("prompt") or label).strip()
            if not action_id or not label or action_id in fixed_ids:
                continue
            dynamic.append(
                {
                    "id": action_id[:40],
                    "label": label[:24],
                    "type": action_type if action_type in {"execute", "export", "refine"} else "refine",
                    "prompt": prompt[:80],
                }
            )

    if len(dynamic) < 2:
        dynamic = _default_plan_actions(plan)[2:]
    return [*fixed, *dynamic[:2]]


def _merge_item_enrichment(item: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """把 LLM 生成的单地点解释安全合并回原 POI。"""

    fallback = _fallback_enrich_item(item)
    merged = dict(item)
    reason = extra.get("recommendation_reason")
    if isinstance(reason, str) and reason.strip():
        merged["recommendation_reason"] = reason.strip()

    options = extra.get("option_prompts")
    if isinstance(options, list) and options:
        merged["option_prompts"] = [str(option).strip() for option in options[:4] if str(option).strip()]

    merged.setdefault("recommendation_reason", fallback["recommendation_reason"])
    merged.setdefault("option_prompts", fallback["option_prompts"])
    return merged


def _full_plan_text(selected: dict[str, Any], ranked_plans: list[dict[str, Any]]) -> str:
    """生成完整规划的 fallback 文本。"""

    if not selected:
        return "暂时没有生成可执行方案，请调整时间、预算或偏好后重试。"

    names = " -> ".join(item["name"] for item in selected.get("items", []))
    issues = normalize_issues(selected.get("issues", []))
    warning_codes = "、".join(sorted({issue["code"] for issue in issues})) or "无"
    timeline_summary = _timeline_summary(selected)
    route_summary = _route_summary(selected)
    alternatives_summary = _alternatives_summary(ranked_plans)
    return (
        f"{selected.get('title', '本地生活方案')}\n"
        f"路线：{names}\n"
        f"方案评分：{selected.get('plan_score', '待计算')}\n"
        f"推荐理由：{selected.get('recommendation_reason', '整体匹配当前需求')}\n"
        f"预计时长：{selected.get('total_duration_minutes')} 分钟\n"
        f"交通：{route_summary}\n"
        f"预计预算：{selected.get('estimated_budget')} 元\n"
        f"校验提醒：{warning_codes}\n"
        f"{alternatives_summary}\n"
        f"{timeline_summary}\n"
        "当前为模拟方案，等待用户确认后可进入执行节点。"
    )


def _alternatives_summary(ranked_plans: list[dict[str, Any]]) -> str:
    """把 3 个方案的优缺点压缩到文本里。"""

    if not ranked_plans:
        return "备选方案：暂无"
    lines = ["备选方案："]
    for index, plan in enumerate(ranked_plans[:3], start=1):
        pros = "；".join(plan.get("pros", [])[:2]) or "偏好匹配度较高"
        cons = "；".join(plan.get("cons", [])[:2]) or "需确认营业和排队"
        lines.append(
            f"{index}. {plan.get('title', '方案')}：{plan.get('recommendation_reason', '')} 优点：{pros}。缺点：{cons}。"
        )
    return "\n".join(lines)


def _llm_response_text(
    state: PlanState,
    fallback_text: str,
    *,
    ranked_plans: list[dict[str, Any]] | None = None,
    selected_plan: dict[str, Any] | None = None,
) -> str | None:
    """让大模型把结构化结果改写成自然语言响应。

    这里限制模型只做表达：它只能使用 PlanState 里已有的方案、地点、路线、预算和错误信息。
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
        "selected_plan": selected_plan if selected_plan is not None else state.get("selected_plan"),
        "ranked_plans": ranked_plans if ranked_plans is not None else state.get("ranked_plans"),
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
                    "如果有 3 个方案，要清楚说明每个方案的推荐理由、优点和缺点。"
                    "每个地点只给一句简短推荐理由，不要写长篇。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(response_context, ensure_ascii=False, default=str),
            },
        ],
        temperature=0.2,
        max_completion_tokens=1600,
    )
    if not raw:
        return None
    text = raw.strip()
    return text or None


def _timeline_summary(selected: dict[str, Any]) -> str:
    """把时间线压缩成文本摘要，方便调用方直接阅读。"""

    timeline = selected.get("timeline", [])
    if not timeline:
        return "时间线：待生成"
    parts = [
        f"{item.get('start_time')}-{item.get('end_time', '待定')} {item.get('title')}"
        for item in timeline[:4]
    ]
    return "时间线：" + "；".join(parts)


def _route_summary(selected: dict[str, Any]) -> str:
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
    """系统能力说明。"""

    return (
        "我可以帮你做三类事情：\n"
        "1. 完整行程规划：根据人数、时间、预算和偏好安排活动、餐厅和路线。\n"
        "2. 分类推荐：只推荐餐厅、电影、按摩、健身、景点、购物等某一类地点。\n"
        "3. 简单问答：说明系统能力、数据源状态和使用方式。\n"
        "如果你想要完整规划，可以说：周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元。"
    )


def _simple_answer_text(query: str) -> str:
    """简单问答兜底文本。"""

    return (
        "我理解这是一个简单询问，不需要启动完整行程规划。\n"
        f"你的问题是：{query}\n"
        "你可以继续问我支持什么功能，或者直接说想推荐哪一类本地生活地点。"
    )

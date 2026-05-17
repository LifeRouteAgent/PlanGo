from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch


def response_generator_node(state: PlanState) -> PlanStatePatch:
    selected = state.get("selected_plan") or {}
    if not selected:
        text = "暂时没有生成可执行方案，请调整时间、预算或偏好后重试。"
    else:
        names = " -> ".join(item["name"] for item in selected.get("items", []))
        text = (
            f"{selected.get('title', '本地生活方案')}\n"
            f"路线：{names}\n"
            f"预计时长：{selected.get('total_duration_minutes')} 分钟\n"
            f"预计预算：{selected.get('estimated_budget')} 元\n"
            "当前为模拟方案，等待用户确认后可进入执行节点。"
        )
    return {"response_text": text, "logs": ["Response Generator: generated response text"]}

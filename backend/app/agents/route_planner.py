from __future__ import annotations

from app.state.plan_state import PlanState, PlanStatePatch


def route_time_planner_node(state: PlanState) -> PlanStatePatch:
    """路线与时间线规划节点。

    输入是各 Skill 推荐出的候选 POI，输出是一个或多个 candidate plan。
    当前仍是 mock 路线，但已经把时间线、路线耗时、预算和异常演示开关拆开，
    后续可以替换为真实高德路线 API。
    """

    recommended = state.get("recommended_pois", {})
    all_candidates = [item for items in recommended.values() for item in items]
    if not all_candidates:
        return {
            "errors": ["candidate_empty"],
            "logs": ["Route & Time Planner: no recommended POIs available"],
        }

    plan_items = _select_plan_items(all_candidates)
    duration_limit = int(state.get("constraints", {}).get("duration_hours", 6)) * 60
    max_route_minutes = int(state.get("constraints", {}).get("max_route_minutes", 45))
    route_minutes = _route_minutes_for_state(state, len(plan_items), max_route_minutes)
    planned_minutes = _planned_minutes_for_state(state, duration_limit, route_minutes)
    timeline = _build_timeline(plan_items, state.get("constraints", {}).get("start_time", "14:00"))
    plan = {
        "id": "plan_mock_1",
        "title": "周末本地生活轻量方案",
        "items": plan_items,
        "timeline": timeline,
        "total_duration_minutes": planned_minutes,
        "route_minutes": route_minutes,
        "estimated_budget": 360,
    }
    route = {
        "mode": "amap_placeholder",
        "total_minutes": route_minutes,
        "segments": max(0, len(plan_items) - 1),
    }
    return {
        "candidate_plans": [plan],
        "routes": [route],
        "logs": ["Route & Time Planner: assembled one candidate timeline"],
    }


def _route_minutes_for_state(state: PlanState, item_count: int, max_route_minutes: int) -> int:
    """生成 mock 路线耗时。

    `force_route_timeout` 只在第一次规划时生效；回退后 Planner 应能重新规划成功。
    """

    if state.get("force_route_timeout") and state.get("replanning_count", 0) <= 1:
        return max_route_minutes + 20
    return max(15, min(max_route_minutes, item_count * 12))


def _planned_minutes_for_state(state: PlanState, duration_limit: int, route_minutes: int) -> int:
    """生成 mock 总时长。

    `force_duration_exceeded` 用于验证 Verifier 的总时长异常和反馈循环。
    """

    if state.get("force_duration_exceeded") and state.get("replanning_count", 0) <= 1:
        return duration_limit + 45
    return min(duration_limit, 180 + route_minutes)


def _build_timeline(items: list[dict], start_time: str) -> list[dict]:
    """构造前端可直接展示的简化时间线。

    当前不做真实时间加减，只保证每个 POI 有明确顺序、类型和展示标题。
    """

    return [
        {
            "order": index + 1,
            "start_time": start_time if index == 0 else "待计算",
            "title": item["name"],
            "category": item["category"],
            "address": item["address"],
        }
        for index, item in enumerate(items)
    ]


def _select_plan_items(candidates: list[dict]) -> list[dict]:
    """选择进入时间线的 POI。

    为了让“餐厅无位”这类异常可被稳定验证，若候选中有餐厅，则确保餐厅进入方案。
    """

    selected = candidates[:3]
    restaurants = [item for item in candidates if item.get("category") == "poi_restaurant"]
    if restaurants and not any(item.get("category") == "poi_restaurant" for item in selected):
        if len(selected) >= 3:
            selected[-1] = restaurants[0]
        else:
            selected.append(restaurants[0])
    return selected

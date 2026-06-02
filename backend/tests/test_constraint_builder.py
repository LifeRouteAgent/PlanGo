from __future__ import annotations

from app.agents.constraint_builder import constraint_builder_node
from app.state.plan_state import create_initial_state


def test_constraint_builder_parses_afternoon_time_range() -> None:
    """本地生活规划应把“下午 2 点到 6 点”识别为 14:00 开始、4 小时窗口。"""

    state = create_initial_state("周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600")

    patch = constraint_builder_node(state)
    constraints = patch["constraints"]

    assert constraints["start_time"] == "14:00"
    assert constraints["duration_hours"] == 4
    assert constraints["budget"] == 600


def test_constraint_builder_keeps_route_limit_soft() -> None:
    """路线偏好只影响排序，不应该阻断方案生成。"""

    state = create_initial_state("周末下午和朋友出去玩，想吃饭唱歌，预算适中，别太远")
    state["constraints"] = {"route_limit_is_hard": True}

    patch = constraint_builder_node(state)
    constraints = patch["constraints"]

    assert constraints["max_route_minutes"] >= 30
    assert constraints["route_limit_is_hard"] is False

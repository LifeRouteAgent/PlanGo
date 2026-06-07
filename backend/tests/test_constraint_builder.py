from __future__ import annotations

from app.planning.services import build_constraints, resolve_intent


def test_v2_constraint_builder_parses_budget_and_uses_defaults() -> None:
    understanding = resolve_intent("周六下午 2 点到 6 点，4 个朋友，想吃饭看电影，预算 600", {}, {})

    constraints, recall = build_constraints(understanding, city="北京", origin=None)

    assert constraints.budget_policy.total_budget == 600
    assert constraints.time_policy.duration_minutes == 240
    assert constraints.rating_policy.min_rating_initial == 4.0
    assert recall.target_slots


def test_v2_constraint_builder_keeps_route_limit_as_policy_not_clarification() -> None:
    understanding = resolve_intent("周末下午和朋友出去玩，想吃饭唱歌，预算适中，别太远", {}, {})

    constraints, _ = build_constraints(understanding, city="北京", origin=None)

    assert constraints.hard_constraints.max_route_minutes >= 30
    assert understanding.intent.request_type == "full_itinerary_plan"

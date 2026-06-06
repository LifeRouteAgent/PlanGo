from __future__ import annotations

from app.graph.services import build_constraints, resolve_intent


def test_followup_budget_context_becomes_plan_adjustment() -> None:
    understanding = resolve_intent("预算改成 1000，其他不变", {}, {"has_active_plan": True})

    constraints, _ = build_constraints(understanding, city="北京", origin=None)

    assert understanding.intent.request_type == "plan_adjustment"
    assert constraints.budget_policy.total_budget == 1000

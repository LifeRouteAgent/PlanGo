from __future__ import annotations

from app.planning.services import rank_route_plans
from app.planning.state import CandidatePlan, FinalConstraints, PlanBudgetSummary, RouteSummary


def test_ranker_only_orders_candidate_plans() -> None:
    constraints = FinalConstraints()
    plans = [
        CandidatePlan(
            plan_id="near",
            generation_strategy="test",
            route_summary=RouteSummary(total_distance_km=2, total_route_minutes=15),
            budget_summary=PlanBudgetSummary(estimated_total_budget=120),
        ),
        CandidatePlan(
            plan_id="far",
            generation_strategy="test",
            route_summary=RouteSummary(total_distance_km=20, total_route_minutes=90),
            budget_summary=PlanBudgetSummary(estimated_total_budget=120),
        ),
    ]

    _, ranked = rank_route_plans(plans, {}, constraints, top_n=2)

    assert [item.plan_id for item in ranked] == ["near", "far"]
    assert ranked[0].rank == 1

from __future__ import annotations

from fastapi import APIRouter

from app.dag.langgraph_dag_config import life_route_graph
from app.models.schemas import TripPlanRequest, TripPlanResponse
from app.state.plan_state import create_initial_state


router = APIRouter(prefix="/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlanResponse)
def plan_trip(request: TripPlanRequest) -> TripPlanResponse:
    initial_state = create_initial_state(
        request.user_query,
        user_profile=request.user_profile,
        max_replanning_count=request.max_replanning_count,
    )
    result = life_route_graph.invoke(initial_state)
    return TripPlanResponse(
        response_text=result.get("response_text", ""),
        execution_status=result.get("execution_status", "unknown"),
        selected_plan=result.get("selected_plan", {}),
        ranked_plans=result.get("ranked_plans", []),
        errors=result.get("errors", []),
        logs=result.get("logs", []),
    )

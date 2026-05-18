from __future__ import annotations

from fastapi import APIRouter

from app.config import settings
from app.dag.langgraph_dag_config import life_route_graph
from app.models.schemas import DataSourceStatusResponse, TripPlanRequest, TripPlanResponse
from app.services.poi_repository import PoiRepository
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
        intent_type=result.get("intent_type", ""),
        answer_mode=result.get("answer_mode", ""),
        need_clarification=result.get("need_clarification", False),
        missing_constraints=result.get("missing_constraints", []),
        clarify_question=result.get("clarify_question", ""),
        selected_plan=result.get("selected_plan", {}),
        ranked_plans=result.get("ranked_plans", []),
        errors=result.get("errors", []),
        logs=result.get("logs", []),
    )


@router.get("/data-source", response_model=DataSourceStatusResponse)
def data_source_status() -> DataSourceStatusResponse:
    """返回当前 POI 数据源状态。

    前端和人工 review 可以用这个接口确认当前是否真的在读取本地 MySQL，
    而不是因为连接失败悄悄降级到 Mock。
    """

    if not settings.use_database:
        return DataSourceStatusResponse(
            enabled=False,
            source="mock",
            database_name=settings.database_name,
        )

    try:
        return DataSourceStatusResponse(
            enabled=True,
            source="mysql",
            database_name=settings.database_name,
            table_counts=PoiRepository().table_counts(),
        )
    except Exception as exc:  # noqa: BLE001 - 健康检查接口需要把数据库异常转成可读状态
        return DataSourceStatusResponse(
            enabled=False,
            source="mysql_error",
            database_name=settings.database_name,
            error=str(exc),
        )

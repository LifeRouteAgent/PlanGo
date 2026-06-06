from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.schemas.trip import TripPlanRequest
from app.planning.trip_services import start_v2_plan_progress
from app.streaming.sse import progress_streaming_response

router = APIRouter(prefix="/api/plans", tags=["planning-progress"])


@router.post("")
def create_plan_progress_stream(request: TripPlanRequest) -> dict[str, str]:
    return start_v2_plan_progress(request)


@router.get("/{request_id}/stream")
def stream_plan_progress(request_id: str) -> StreamingResponse:
    return progress_streaming_response(request_id)

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

from app.streaming.stream_manager import stream_manager


def sse_encode(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def progress_event_stream(request_id: str) -> AsyncIterator[str]:
    target = stream_manager
    async for item in target.listen(request_id):
        if isinstance(item, dict) and item.get("type") == "heartbeat":
            yield sse_encode("heartbeat", item)
            continue
        event_type = "progress"
        if isinstance(item, dict):
            item_type = item.get("type", "")
            if item_type in {"final", "final_result", "error"}:
                event_type = item_type
        yield sse_encode(event_type, item if isinstance(item, dict) else {"message": str(item)})


def progress_streaming_response(request_id: str) -> StreamingResponse:
    return StreamingResponse(
        progress_event_stream(request_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

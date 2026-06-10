from __future__ import annotations

import asyncio
import time

from app.bus.event import Event, EventType
from app.bus.event_bus import InMemoryEventBus, publish_event_sync
from app.bus.subscribers.frontend_subscriber import FrontendSubscriber
from app.bus.subscribers.progress_projector import ProgressProjector
from app.api.schemas.trip import TripPlanRequest
from app.planning.trip_services import start_v2_plan_progress
from app.streaming.sse import sse_encode
from app.streaming.stream_manager import StreamManager


def test_event_bus_subscribe_and_publish() -> None:
    async def run() -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []
        bus.subscribe("run_started", lambda event: seen.append(event.event_type))

        await bus.publish(Event(event_type=EventType.RUN_STARTED, request_id="req_1"))

        assert seen == [EventType.RUN_STARTED]

    asyncio.run(run())


def test_event_bus_wildcard_subscription() -> None:
    async def run() -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []
        bus.subscribe("*", lambda event: seen.append(event.event_type))

        await bus.publish(Event(event_type=EventType.NODE_STARTED, request_id="req_1"))
        await bus.publish(Event(event_type=EventType.POI_RECALLED, request_id="req_1"))

        assert seen == [EventType.NODE_STARTED, EventType.POI_RECALLED]

    asyncio.run(run())


def test_progress_projector_maps_and_sanitizes_events() -> None:
    event = Event(
        event_type=EventType.TOOL_FAILED,
        request_id="req_1",
        payload={
            "traceback": "Traceback: secret stack",
            "sql": "SELECT * FROM users",
            "total_count": 100,
        },
    )

    progress = ProgressProjector().project(event)

    assert progress is not None
    assert progress.type == "warning"
    assert "Traceback" not in progress.message
    assert "sql" not in progress.data
    assert progress.data["total_count"] == 100


def test_frontend_subscriber_pushes_projected_event_not_raw_event() -> None:
    async def run() -> None:
        manager = StreamManager()
        manager.register("req_1")
        subscriber = FrontendSubscriber(ProgressProjector(), manager)

        await subscriber.handle(
            Event(
                event_type=EventType.NODE_STARTED,
                request_id="req_1",
                node_name="collector",
                payload={"sql": "SELECT * FROM poi_restaurant"},
            )
        )
        await manager.close("req_1")
        items = []
        async for item in manager.listen("req_1", heartbeat_seconds=0.01):
            items.append(item)

        assert items
        assert items[0]["title"] == "正在查找候选地点"
        assert "event_type" not in items[0]
        assert "sql" not in items[0].get("data", {})

    asyncio.run(run())


def test_stream_manager_send_and_close() -> None:
    async def run() -> None:
        manager = StreamManager()
        manager.register("req_1")
        await manager.send("req_1", {"type": "progress", "title": "t"})
        await manager.close("req_1")

        items = []
        async for item in manager.listen("req_1", heartbeat_seconds=0.01):
            items.append(item)

        assert items == [{"type": "progress", "title": "t"}]

    asyncio.run(run())


def test_sse_encode_format() -> None:
    text = sse_encode("progress", {"title": "正在处理"})

    assert text.startswith("event: progress\n")
    assert "data: " in text
    assert text.endswith("\n\n")


def test_large_payload_does_not_enter_frontend_event() -> None:
    event = Event(
        event_type=EventType.POI_RECALLED,
        request_id="req_1",
        payload={"items": [{"name": str(index)} for index in range(300)], "total_count": 300},
    )

    progress = ProgressProjector().project(event)

    assert progress is not None
    assert progress.data == {"total_count": 300}


def test_background_plan_progress_stream_receives_key_events(monkeypatch) -> None:
    import app.planning.trip_services as trip_services

    def fake_run(initial):
        for event_type, node_name, payload in [
            (EventType.RUN_STARTED, None, {}),
            (EventType.NODE_STARTED, "collector", {}),
            (EventType.POI_RECALLED, "collector", {"total_count": 42}),
            (EventType.PLAN_GENERATED, "route_planner", {"plan_count": 5}),
            (EventType.RUN_FINISHED, None, {"plan_count": 3}),
        ]:
            publish_event_sync(
                Event(
                    event_type=event_type,
                    request_id=initial.state_meta.request_id,
                    run_id=initial.state_meta.state_id,
                    node_name=node_name,
                    status="success",
                    payload=payload,
                )
            )
            time.sleep(0.01)
        return {"ranked_plans": []}

    monkeypatch.setattr(trip_services, "run_v2_state_to_legacy", fake_run)
    created = start_v2_plan_progress(TripPlanRequest(user_query="周末出去玩"))

    async def collect() -> list[dict]:
        items: list[dict] = []
        async for item in trip_services.stream_manager.listen(
            created["request_id"], heartbeat_seconds=0.05
        ):
            items.append(item)
        return items

    items = asyncio.run(collect())
    titles = [item.get("title") for item in items]

    assert "规划已启动" in titles
    assert "正在查找候选地点" in titles
    assert "已找到候选地点" in titles
    assert "已生成初步方案" in titles
    assert "规划完成" in titles

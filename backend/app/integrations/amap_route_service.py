from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.tools.tool_harness import ToolHarness
from app.tools.tool_policy import ToolCallRequest, ToolCallResult


@dataclass(frozen=True)
class AmapRouteEstimate:
    """高德路线接口返回的单段路线估算结果。

    Route Planner 只关心距离、耗时和数据来源，不直接依赖高德原始 JSON。
    """

    distance_km: float
    duration_minutes: int
    source: str
    polyline: list[dict[str, float]] = field(default_factory=list)


class AmapRouteService:
    """高德路线服务适配器。

    当前只接入步行和驾车两个最稳定的接口：
    - 1km 内优先步行。
    - 1km 以上优先驾车，用于近似打车/自驾耗时。

    公交/地铁接口通常需要城市编码和更复杂的换乘结构，后续可以在这里扩展，
    Route Planner 不需要改调用方式。
    """

    def __init__(self, api_key: str | None = None, *, timeout_seconds: float = 2.5) -> None:
        self._api_key = api_key if api_key is not None else settings.amap_api_key
        self._timeout_seconds = timeout_seconds
        self.call_log: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        """只有显式开启路线修正且配置 key 时才调用高德。

        前端地图展示只需要 AMAP_API_KEY；路线修正属于外部工具调用，默认关闭可以让单元测试和 demo
        在无网络或高德限流时保持稳定。需要真实路线时，在 config.local.toml 里设置
        AMAP_ROUTE_ENABLED=true。
        """

        return bool(self._api_key) and settings.amap_route_enabled

    def estimate_segment(
        self,
        previous: dict[str, Any],
        current: dict[str, Any],
        *,
        fallback_distance_km: float,
    ) -> AmapRouteEstimate | None:
        """估算两个 POI 之间的真实路线距离和耗时。

        高德要求经纬度格式为 `lon,lat`。如果接口异常、key 缺失、返回状态失败，
        统一返回 None，由 Route Planner 使用 Haversine 结果兜底。
        """

        harness = ToolHarness(
            name="amap.route.estimate_segment",
            timeout_seconds=self._timeout_seconds + 0.5,
            max_retries=1,
            fallback=lambda *_args, **_kwargs: _fallback_estimate(fallback_distance_km),
        )
        if not self.enabled:
            result = harness.run_request(
                ToolCallRequest(
                    tool_name="amap.route.estimate_segment",
                    risk_level=1,
                    params={"enabled": False, "fallback_distance_km": fallback_distance_km},
                ),
                lambda: _fallback_estimate(fallback_distance_km),
            )
            self.call_log.extend(harness.call_log)
            return _route_result_data(result) or _fallback_estimate(fallback_distance_km)

        result = harness.run_request(
            ToolCallRequest(
                tool_name="amap.route.estimate_segment",
                risk_level=1,
                params={
                    "origin": _safe_route_point(previous),
                    "destination": _safe_route_point(current),
                    "fallback_distance_km": fallback_distance_km,
                },
            ),
            self._estimate_segment_live,
            previous,
            current,
            fallback_distance_km,
        )
        self.call_log.extend(harness.call_log)
        return (
            _route_result_data(result)
            if result.success
            else _fallback_estimate(fallback_distance_km)
        )

    def _estimate_segment_live(
        self,
        previous: dict[str, Any],
        current: dict[str, Any],
        fallback_distance_km: float,
    ) -> AmapRouteEstimate:
        """执行真实高德路线调用，失败时抛出异常交给 ToolHarness 处理。"""

        origin = _format_location(previous)
        destination = _format_location(current)
        estimate = (
            self._walking(origin, destination)
            if fallback_distance_km <= 1
            else self._driving(origin, destination)
        )
        if estimate is None:
            raise ValueError("amap route response has no usable path")
        return estimate

    def _walking(self, origin: str, destination: str) -> AmapRouteEstimate | None:
        """调用高德步行路线接口。"""

        data = self._get(
            "https://restapi.amap.com/v3/direction/walking",
            {"origin": origin, "destination": destination},
        )
        paths = data.get("route", {}).get("paths", [])
        if not paths:
            return None
        first = paths[0]
        return _estimate_from_meters_seconds(
            first.get("distance"),
            first.get("duration"),
            source="amap_walking",
            polyline=_polyline_from_path(first),
        )

    def _driving(self, origin: str, destination: str) -> AmapRouteEstimate | None:
        """调用高德驾车路线接口，作为打车/自驾耗时近似。"""

        data = self._get(
            "https://restapi.amap.com/v3/direction/driving",
            {
                "origin": origin,
                "destination": destination,
                # strategy=10 表示尽量使用默认速度优先策略，避免过度绕行。
                "strategy": "10",
            },
        )
        paths = data.get("route", {}).get("paths", [])
        if not paths:
            return None
        first = paths[0]
        return _estimate_from_meters_seconds(
            first.get("distance"),
            first.get("duration"),
            source="amap_driving",
            polyline=_polyline_from_path(first),
        )

    def _get(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        """执行高德 GET 请求，并校验通用状态字段。"""

        response = httpx.get(
            url,
            params={**params, "key": self._api_key or "", "output": "JSON"},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if str(data.get("status")) != "1":
            return {}
        return data


def _format_location(poi: dict[str, Any]) -> str:
    """把统一 POI 坐标转换成高德 API 要求的 `lon,lat`。"""

    return f"{float(poi['lon'])},{float(poi['lat'])}"


def _safe_route_point(poi: dict[str, Any]) -> dict[str, Any]:
    """给 ToolHarness trace 使用的脱敏路线点。"""

    return {
        "id": poi.get("id"),
        "name": poi.get("name"),
        "lat": poi.get("lat"),
        "lon": poi.get("lon"),
    }


def _route_result_data(result: ToolCallResult) -> AmapRouteEstimate | None:
    data = result.data
    if isinstance(data, AmapRouteEstimate):
        return data
    if isinstance(data, dict) and isinstance(data.get("value"), AmapRouteEstimate):
        return data["value"]
    if isinstance(data, dict) and {"distance_km", "duration_minutes", "source"} <= set(data):
        return AmapRouteEstimate(
            distance_km=float(data["distance_km"]),
            duration_minutes=int(data["duration_minutes"]),
            source=str(data["source"]),
            polyline=data.get("polyline", []),
        )
    return None


def _estimate_from_meters_seconds(
    distance: Any,
    duration: Any,
    *,
    source: str,
    polyline: list[dict[str, float]] | None = None,
) -> AmapRouteEstimate | None:
    """把高德米/秒字段归一成公里/分钟。"""

    distance_meters = float(distance)
    duration_seconds = float(duration)
    if distance_meters <= 0 or duration_seconds <= 0:
        return None
    return AmapRouteEstimate(
        distance_km=round(distance_meters / 1000, 2),
        duration_minutes=max(1, round(duration_seconds / 60)),
        source=source,
        polyline=polyline or [],
    )


def _polyline_from_path(path: dict[str, Any]) -> list[dict[str, float]]:
    """从高德路径 steps 中提取前端可绘制的经纬度折线。"""

    points: list[dict[str, float]] = []
    for step in path.get("steps", []) or []:
        polyline = str(step.get("polyline") or "")
        for raw_point in polyline.split(";"):
            if "," not in raw_point:
                continue
            lon_text, lat_text = raw_point.split(",", 1)
            try:
                points.append({"lng": float(lon_text), "lat": float(lat_text)})
            except ValueError:
                continue
    return points


def _fallback_estimate(distance_km: float) -> AmapRouteEstimate:
    """高德不可用时的 Haversine 降级耗时估算。"""

    if distance_km <= 1:
        duration = max(8, round(distance_km / 4.5 * 60) + 3)
    elif distance_km <= 5:
        duration = max(10, round(distance_km / 25 * 60) + 8)
    elif distance_km <= 15:
        duration = max(25, round(distance_km / 22 * 60) + 12)
    else:
        duration = max(50, round(distance_km / 28 * 60) + 15)
    return AmapRouteEstimate(
        distance_km=round(distance_km, 2),
        duration_minutes=int(duration),
        source="fallback_haversine",
        polyline=[],
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass(frozen=True)
class AmapRouteEstimate:
    """高德路线接口返回的单段路线估算结果。

    Route Planner 只关心距离、耗时和数据来源，不直接依赖高德原始 JSON。
    """

    distance_km: float
    duration_minutes: int
    source: str


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

    @property
    def enabled(self) -> bool:
        """只有配置了 key 时才尝试调用高德，避免本地测试误触发网络请求。"""

        return bool(self._api_key)

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

        if not self.enabled:
            return None

        origin = _format_location(previous)
        destination = _format_location(current)
        try:
            if fallback_distance_km <= 1:
                return self._walking(origin, destination)
            return self._driving(origin, destination)
        except httpx.HTTPError, KeyError, TypeError, ValueError:
            return None

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


def _estimate_from_meters_seconds(
    distance: Any,
    duration: Any,
    *,
    source: str,
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
    )

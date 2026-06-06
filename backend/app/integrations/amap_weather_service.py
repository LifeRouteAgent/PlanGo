from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.tools.tool_harness import ToolHarness


class AmapWeatherService:
    """高德天气 Web 服务适配器。

    高德天气接口使用 `city` 和 `key` 查询，`extensions=base` 返回实时天气，
    `extensions=all` 返回预报。这里优先实时天气，失败时返回稳定 fallback，
    避免天气接口影响主规划链路。
    """

    def __init__(self, api_key: str | None = None, *, timeout_seconds: float = 2.5) -> None:
        self._api_key = api_key if api_key is not None else settings.amap_api_key
        self._timeout_seconds = timeout_seconds
        self.call_log: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def current_weather(self, city: str | None) -> dict[str, Any]:
        city_code = _city_code(city)
        harness = ToolHarness(
            name="amap.weather.current",
            timeout_seconds=self._timeout_seconds + 0.5,
            max_retries=1,
            fallback=lambda: _fallback_weather("unconfigured" if not self.enabled else "error"),
        )
        if not self.enabled:
            result = harness.run_request(
                {
                    "tool_name": "amap.weather.current",
                    "risk_level": 1,
                    "params": {"city": city_code, "enabled": False},
                },
                lambda: _fallback_weather("unconfigured"),
            )
            self.call_log.extend(harness.call_log)
            return _weather_result_data(result) or _fallback_weather("unconfigured")
        result = harness.run_request(
            {
                "tool_name": "amap.weather.current",
                "risk_level": 1,
                "params": {"city": city_code},
            },
            self._current_weather_live,
            city_code,
        )
        self.call_log.extend(harness.call_log)
        return _weather_result_data(result) if result.get("success") else _fallback_weather("error")

    def _current_weather_live(self, city_code: str) -> dict[str, Any]:
        response = httpx.get(
            "https://restapi.amap.com/v3/weather/weatherInfo",
            params={
                "key": self._api_key,
                "city": city_code,
                "extensions": "base",
                "output": "JSON",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if str(data.get("status")) != "1":
            raise ValueError(str(data.get("info") or "amap weather failed"))
        lives = data.get("lives") or []
        if not lives:
            raise ValueError("amap weather response has no lives")
        live = lives[0]
        temperature = _safe_int(live.get("temperature"))
        weather = str(live.get("weather") or "天气未知")
        wind = str(live.get("winddirection") or "")
        humidity = str(live.get("humidity") or "")
        return {
            "temperature_c": temperature,
            "condition": weather,
            "icon": _weather_icon(weather),
            "summary": (
                f"{live.get('province', '')}{live.get('city', '')}实时天气：{weather}"
                + (f"，{temperature}°C" if temperature is not None else "")
                + (f"，{wind}风，湿度 {humidity}%" if humidity else "")
            ),
            "source": "amap",
            "hourly": [],
            "message": str(live.get("reporttime") or ""),
        }


def _city_code(city: str | None) -> str:
    value = str(city or "").lower()
    if value in {"beijing", "北京", "北京市", "110000", "110100"}:
        return "110000"
    return city or "110000"


def _weather_result_data(result: dict[str, Any]) -> dict[str, Any] | None:
    data = result.get("data")
    if isinstance(data, dict) and "value" in data and isinstance(data["value"], dict):
        return data["value"]
    return data if isinstance(data, dict) else None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except TypeError, ValueError:
        return None


def _weather_icon(weather: str) -> str:
    if "雨" in weather:
        return "🌧️"
    if "雪" in weather:
        return "❄️"
    if "云" in weather or "阴" in weather:
        return "☁️"
    if "晴" in weather:
        return "☀️"
    return "🌤️"


def _fallback_weather(source: str) -> dict[str, Any]:
    return {
        "temperature_c": None,
        "condition": "天气未启用" if source == "unconfigured" else "天气获取失败",
        "icon": "🌤️",
        "summary": "暂未获取到高德实时天气，方案仍按用户输入和室内外偏好执行。",
        "source": source,
        "hourly": [],
        "message": "",
    }

"""Weather for modules — read through Hub from Hecate (the only one that talks to the weather service).

    from hestia_common.weather_client import WeatherClient, is_rainy, day_summary
    w = WeatherClient()
    f = w.forecast(place="", date_from="2026-10-21")      # place "" = Marko's Casa
    if f.get("status") == "ok": ...

Fail soft: any problem (no place, out of range, Hecate or the provider away) answers ``{"status": <reason>}``
and is logged once; callers simply go on without weather.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger("hestia_common.weather")

RAIN_PROB = 50     # % from which a day/hour counts as rainy
RAIN_MM = 1.0      # mm from which a day counts as rainy


def _hub_default() -> str:
    return os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")


def is_rainy(row: dict | None) -> bool:
    """«It rains» for a day or hour row of Hecate's answers."""
    if not row:
        return False
    return (row.get("rain_prob") or 0) >= RAIN_PROB or (row.get("rain_mm") or 0) >= RAIN_MM


def day_summary(day: dict | None) -> str:
    """``12–19°, pioggia 15–17`` (short Italian line for texts)."""
    if not day:
        return ""
    out = f"{day.get('min_c')}–{day.get('max_c')}°, {day.get('condition') or ''}".rstrip(", ")
    hours = day.get("rain_hours") or []
    if hours:
        out += f", pioggia {hours[0]}–{hours[-1]}" if len(hours) > 1 else f", pioggia alle {hours[0]}"
    return out


class WeatherClient:
    def __init__(self, hub_api_url: str | None = None, timeout: float = 6):
        self.hub = (hub_api_url or _hub_default()).rstrip("/")
        self.timeout = timeout

    def _route(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> dict:
        try:
            resp = requests.post(f"{self.hub}/route/hecate/{path.lstrip('/')}",
                                 json={"method": method, "headers": {}, "query": query or {}, "body": body,
                                       "timeout_seconds": self.timeout}, timeout=self.timeout + 2)
            routed = resp.json() if resp.content else {}
            status = int((routed or {}).get("status_code") or resp.status_code)
            payload = (routed or {}).get("payload")
            if status >= 400 or not isinstance(payload, dict):
                raise RuntimeError(f"HTTP {status}")
            return payload
        except Exception as exc:
            logger.warning("[🔄] event=weather_client_failed path=%s error=%s fallback=no_weather", path, exc)
            return {"status": "unavailable", "error": str(exc)}

    def now(self, place: str = "") -> dict:
        return self._route("GET", "api/gateway/weather/now", {"place": place} if place else {})

    def forecast(self, place: str = "", date_from: str = "", date_to: str = "", hourly: bool = False) -> dict:
        q = {k: v for k, v in {"place": place, "date_from": date_from, "date_to": date_to}.items() if v}
        if hourly:
            q["hourly"] = "true"
        return self._route("GET", "api/gateway/weather/forecast", q)

    def at(self, items: list[dict]) -> dict[str, Any]:
        """``{key: answer}`` for ``[{key, place?, at?, date?}]`` (empty dict when unavailable)."""
        out = self._route("POST", "api/gateway/weather/at", body={"items": items})
        return out.get("items") or {} if out.get("status") == "ok" else {}

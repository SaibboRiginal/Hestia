"""Device feeds: data from the owner's devices pushed to the modules that asked for it.

Dossier ``docs/work/2026-10-24-tutto-brainstorm-cindy`` W4 (B10 Garmin, Cindy 32 phone as a sensor). Hecate owns the
devices (Garmin account, the phone's webhook); it never decides what the data means. A module that wants a kind of
data declares it in its Hub registration and Hecate pushes every new item to it through the Hub (push, not poll):

    from hestia_common.feeds import capabilities as feed_capabilities
    caps.update(feed_capabilities({"wearable.daily": "/api/hercules/wearable"}))

    # Hecate
    feeds = FeedPublisher(HUB_API_URL)
    feeds.publish("wearable.daily", {"date": "2026-10-29", "sleep": {...}, "activities": [...]})

Kinds:
- ``wearable.daily``: one day of watch data ``{date, source, sleep, steps, resting_hr, body_battery, hrv, readiness,
  stress_avg, activities}`` (any part may be missing);
- ``phone.notification``: an app notification on the phone ``{app, title, text, at}``;
- ``phone.state``: what the phone says about the owner ``{home, wifi, charging, battery, at}``.
A subscriber answers 2xx; a failure is logged (``[🔄]``) and the next push/sync carries the data again.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

logger = logging.getLogger("hestia_common.feeds")

KINDS = ("wearable.daily", "phone.notification", "phone.state")
CAPABILITY = "feeds"
_CACHE_S = 60


def capabilities(feeds: dict[str, str]) -> dict[str, dict[str, str]]:
    """``{kind: path}`` the module receives (POST, body = the item)."""
    for kind, path in feeds.items():
        if kind not in KINDS:
            raise ValueError(f"feed kind {kind!r} must be one of {KINDS}")
        if not str(path).startswith("/"):
            raise ValueError(f"feed path {path!r} must start with /")
    return {CAPABILITY: dict(feeds)}


class FeedPublisher:
    def __init__(self, hub_api_url: str, *, session: Any = None):
        self.hub = hub_api_url.rstrip("/")
        self._http = session or requests.Session()
        self._lock = threading.Lock()
        self._cache: tuple[float, list[dict]] = (0.0, [])

    def _services(self) -> list[dict]:
        with self._lock:
            if time.monotonic() - self._cache[0] < _CACHE_S:
                return self._cache[1]
        resp = self._http.get(f"{self.hub}/registry/services", timeout=6)
        resp.raise_for_status()
        services = (resp.json() or {}).get("services") or []
        services = services if isinstance(services, list) else []
        with self._lock:
            self._cache = (time.monotonic(), services)
        return services

    def subscribers(self, kind: str) -> list[tuple[str, str]]:
        out = []
        for svc in self._services():
            name = str((svc or {}).get("name") or "").strip()
            path = str((((svc or {}).get("capabilities") or {}).get(CAPABILITY) or {}).get(kind) or "").strip()
            if name and path and str((svc or {}).get("status") or "online").lower() != "offline":
                out.append((name, path))
        return sorted(set(out))

    def publish(self, kind: str, item: dict, *, timeout: float = 15) -> dict[str, list[str]]:
        """Push one item to every subscriber of ``kind`` → ``{delivered: [svc], failed: [svc]}``."""
        if kind not in KINDS:
            raise ValueError(f"feed kind {kind!r} must be one of {KINDS}")
        try:
            subs = self.subscribers(kind)
        except Exception as exc:
            logger.warning("[🔄] event=feed_discovery_failed kind=%s error=%s fallback=next_push", kind, exc)
            return {"delivered": [], "failed": ["hub"]}
        delivered, failed = [], []
        for service, path in subs:
            try:
                resp = self._http.post(f"{self.hub}/route/{service}/{path.lstrip('/')}",
                                       json={"method": "POST", "headers": {}, "query": {}, "body": item,
                                             "timeout_seconds": timeout}, timeout=timeout + 4)
                resp.raise_for_status()
                status = int((resp.json() or {}).get("status_code", 500))
            except Exception as exc:
                logger.warning("[🔄] event=feed_push_failed kind=%s service=%s error=%s fallback=next_push",
                               kind, service, exc)
                failed.append(service)
                continue
            (delivered if status < 400 else failed).append(service)
            if status >= 400:
                logger.warning("[🔄] event=feed_push_failed kind=%s service=%s status=%s fallback=next_push",
                               kind, service, status)
        logger.info("event=feed_published kind=%s delivered=%d failed=%d", kind, len(delivered), len(failed))
        return {"delivered": delivered, "failed": failed}

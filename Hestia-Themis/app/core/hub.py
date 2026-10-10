"""Hub routing (the only door): ``POST {HUB}/route/<svc>/<path>`` with the standard envelope."""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("hestia_themis.hub")


class HubError(RuntimeError):
    def __init__(self, status: int, payload: Any = None):
        super().__init__(f"status {status}")
        self.status = status
        self.payload = payload


class Hub:
    def __init__(self, hub_api_url: str):
        self.base = hub_api_url.rstrip("/")
        self._session = requests.Session()

    def call(self, service: str, method: str, path: str, *, body: Any = None, query: dict | None = None,
             timeout: float = 8) -> tuple[int, Any]:
        """Return ``(status_code, payload)`` of the target; raises on transport failure."""
        resp = self._session.post(
            f"{self.base}/route/{service}/{path.lstrip('/')}",
            json={"method": method.upper(), "headers": {}, "query": {k: v for k, v in (query or {}).items()
                                                                       if v is not None},
                  "body": body, "timeout_seconds": timeout},
            timeout=timeout + 3)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def ok(self, service: str, method: str, path: str, **kw) -> Any:
        """Like ``call`` but raises ``HubError`` on a non-2xx answer."""
        status, payload = self.call(service, method, path, **kw)
        if status >= 400:
            raise HubError(status, payload)
        return payload

    def status(self) -> list[dict]:
        """Registered services with their health (Hub ``/status``), for the module status cards."""
        try:
            resp = self._session.get(f"{self.base}/status", timeout=8)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                data = data.get("services") or data.get("items") or []
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("[🔄] event=themis_hub_status_failed error=%s", exc)
            return []

"""Client discovery — who receives Hermes notifications.

A client is any service registered on Hub with topology tag ``layer:client``
that declares ``capabilities.notify_endpoint`` (e.g. Telegram, WebUI). Hermes
never hardcodes a client: a new one only has to register (SPEC §5.2).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger("hestia_hermes.clients")

_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class NotifyClient:
    name: str            # Hub service name, used for /route/<name>/...
    endpoint: str        # notify_endpoint path, e.g. /api/notify


class ClientRegistry:
    def __init__(self, hub_api_url: str | None = None):
        self.hub_api_url = (hub_api_url or os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")
        self._lock = threading.Lock()
        self._clients: list[NotifyClient] = []
        self._loaded_at = 0.0
        self._revision: int | None = None

    def _current_revision(self) -> int | None:
        try:
            resp = requests.get(f"{self.hub_api_url}/registry/revision", timeout=3)
            if resp.status_code < 400:
                return int((resp.json() or {}).get("revision"))
        except Exception:
            pass
        return None

    def _load(self) -> list[NotifyClient] | None:
        try:
            resp = requests.get(f"{self.hub_api_url}/registry/services", timeout=4)
            if resp.status_code >= 400:
                return None
            services = (resp.json() or {}).get("services") or []
        except Exception as exc:
            logger.warning("[🔄] event=client_discovery_failed error=%s", exc)
            return None
        found: dict[str, NotifyClient] = {}
        for svc in services if isinstance(services, list) else []:
            if not isinstance(svc, dict):
                continue
            if "layer:client" not in (svc.get("topology_tags") or []):
                continue
            caps = svc.get("capabilities") or {}
            endpoint = str(caps.get("notify_endpoint") or "").strip() if isinstance(caps, dict) else ""
            name = str(svc.get("name") or "").strip()
            if name and endpoint.startswith("/"):
                found[name] = NotifyClient(name=name, endpoint=endpoint)
        return sorted(found.values(), key=lambda c: c.name)

    def clients(self, force: bool = False) -> list[NotifyClient]:
        """Cached list; reloaded when the Hub registry revision changes or the TTL expires."""
        now = time.monotonic()
        with self._lock:
            fresh = self._clients and (now - self._loaded_at) < _CACHE_TTL_SECONDS
        if fresh and not force:
            revision = self._current_revision()
            if revision is None or revision == self._revision:
                return list(self._clients)
        else:
            revision = self._current_revision()
        loaded = self._load()
        with self._lock:
            if loaded is not None:
                if [c.name for c in loaded] != [c.name for c in self._clients]:
                    logger.info("event=notify_clients_discovered clients=%s",
                                ",".join(c.name for c in loaded) or "-")
                self._clients = loaded
                self._loaded_at = now
                self._revision = revision
            return list(self._clients)

    def get(self, name: str) -> NotifyClient | None:
        return next((c for c in self.clients() if c.name == name), None)

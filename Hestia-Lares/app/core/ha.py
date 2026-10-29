"""Home Assistant client: REST for states and services, websocket for the push of state changes.

Only Lares talks to Home Assistant. ``LARES_HA_URL`` (e.g. ``http://homeassistant.local:8123``) and
``LARES_HA_TOKEN`` (a long-lived access token) are infrastructure/secret, so they stay in env.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import requests

logger = logging.getLogger("hestia_lares.ha")


class HAError(RuntimeError):
    pass


class HomeAssistant:
    def __init__(self, url: str, token: str, *, session: Any = None):
        self.url = (url or "").rstrip("/")
        self.token = token or ""
        self.http = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def _req(self, method: str, path: str, body: Any = None, timeout: float = 10) -> Any:
        if not self.configured:
            raise HAError("casa non collegata")
        try:
            resp = self.http.request(method, f"{self.url}{path}", json=body, timeout=timeout,
                                     headers={"Authorization": f"Bearer {self.token}"})
        except requests.RequestException as exc:
            raise HAError(f"casa non raggiungibile: {exc}") from exc
        if resp.status_code == 401:
            raise HAError("token della casa non valido")
        if resp.status_code >= 400:
            raise HAError(f"la casa ha risposto {resp.status_code}")
        return resp.json() if resp.content else None

    def states(self) -> list[dict]:
        return self._req("GET", "/api/states") or []

    def call(self, domain: str, service: str, data: dict) -> Any:
        return self._req("POST", f"/api/services/{domain}/{service}", data)

    # ── push: the websocket stream of state_changed ─────────────────────────
    def ws_url(self) -> str:
        return ("wss://" + self.url[8:] if self.url.startswith("https://") else "ws://" + self.url.removeprefix("http://")) \
            + "/api/websocket"

    def listen(self, on_change: Callable[[dict], Any], on_connect: Callable[[], Any] | None = None,
               stop: threading.Event | None = None) -> None:
        """Blocking: auth, subscribe to ``state_changed``, call ``on_change(new_state)``; reconnects with backoff."""
        from websockets.sync.client import connect
        stop = stop or threading.Event()
        delay = 5
        while not stop.is_set():
            if not self.configured:
                stop.wait(300)
                continue
            try:
                with connect(self.ws_url(), open_timeout=10, max_size=8 * 1024 * 1024) as ws:
                    json.loads(ws.recv())                                    # auth_required
                    ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    if json.loads(ws.recv()).get("type") != "auth_ok":
                        raise HAError("token della casa non valido")
                    ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                    logger.info("event=lares_ws_connected")
                    delay = 5
                    if on_connect:
                        on_connect()
                    while not stop.is_set():
                        msg = json.loads(ws.recv())
                        new = ((msg.get("event") or {}).get("data") or {}).get("new_state")
                        if msg.get("type") == "event" and new:
                            on_change(new)
            except Exception as exc:
                logger.warning("[🔄] event=lares_ws_lost error=%s retry_in=%ds", exc, delay)
                stop.wait(delay)
                delay = min(300, delay * 2)

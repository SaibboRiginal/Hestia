"""Home Assistant client: REST for states and services, websocket for the push of state changes.

Only Lares talks to Home Assistant. It is linked from the «Home Assistant» card (Connections,
``hestia_common.connections``): the address (e.g. ``http://homeassistant.local:8123``) is the Themis setting
``lares.home_assistant.address``, the long-lived access token is ``LARES_KEY_HOME_ASSISTANT`` in Lares' .env.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import requests
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_lares.ha")


class HAError(RuntimeError):
    pass


class HomeAssistant:
    def __init__(self, url: str, token: str, *, session: Any = None):
        self.url = (url or "").rstrip("/")
        self.token = token or ""
        self.http = session or requests.Session()
        self._ws: Any = None
        self._wake = threading.Event()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def configure(self, url: str, token: str) -> None:
        """The card saved a new address or token: the push stream reconnects with them."""
        changed = (url or "").rstrip("/") != self.url or (token or "") != self.token
        self.url, self.token = (url or "").rstrip("/"), token or ""
        if changed:
            ws, self._ws = self._ws, None
            if ws is not None:
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass
            self._wake.set()
        logger.info("event=lares_ha_configured configured=%s changed=%s", self.configured, changed)

    def probe(self, url: str, token: str) -> dict:
        """The «Test» button: does Home Assistant answer with this token, how many devices → ``{ok, detail, facts}``."""
        other = HomeAssistant(url, token, session=self.http)
        if not other.url:
            return {"ok": False, "detail": tr("Type the Home Assistant address first."), "facts": []}
        if not other.token:
            return {"ok": False, "detail": tr("The access token is missing."), "facts": []}
        try:
            info = other._req("GET", "/api/config", timeout=8) or {}
            states = other.states()
        except HAError as exc:
            return {"ok": False, "detail": str(exc), "facts": [
                tr("Home Assistant → your profile → Security → Long-lived access tokens → Create token.")]}
        facts = []
        if info.get("version"):
            facts.append(tr("Home Assistant {0}", info["version"]))
        if info.get("location_name"):
            facts.append(tr("Home: {0}", info["location_name"]))
        facts.append(tr("{0} devices and sensors", len(states)))
        return {"ok": True, "detail": tr("Home Assistant answers."), "facts": facts}

    def _req(self, method: str, path: str, body: Any = None, timeout: float = 10) -> Any:
        if not self.configured:
            raise HAError(tr("home not linked"))
        try:
            resp = self.http.request(method, f"{self.url}{path}", json=body, timeout=timeout,
                                     headers={"Authorization": f"Bearer {self.token}"})
        except requests.RequestException as exc:
            raise HAError(tr("home not reachable: {0}", exc)) from exc
        if resp.status_code == 401:
            raise HAError(tr("invalid home token"))
        if resp.status_code >= 400:
            raise HAError(tr("the home answered {0}", resp.status_code))
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
                self._wake.wait(300)
                self._wake.clear()
                continue
            try:
                with connect(self.ws_url(), open_timeout=10, max_size=8 * 1024 * 1024) as ws:
                    self._ws = ws
                    json.loads(ws.recv())                                    # auth_required
                    ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                    if json.loads(ws.recv()).get("type") != "auth_ok":
                        raise HAError(tr("invalid home token"))
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
                if self._wake.is_set():            # closed by configure(): reconnect at once with the new values
                    self._wake.clear()
                    delay = 5
                    continue
                logger.warning("[🔄] event=lares_ws_lost error=%s retry_in=%ds", exc, delay)
                stop.wait(delay)
                delay = min(300, delay * 2)

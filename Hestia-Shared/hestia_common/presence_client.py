"""Assistant presence client — report facts, ask effects (Chronos, through Hub).

SPEC docs/work/2026-10-10-assistant-presence. Modules never test state names: they ask an
**effect** and Chronos decides from the data-defined states, so a new state needs no change here.

```python
from hestia_common.presence_client import PresenceClient

presence = PresenceClient("hephaestus")
presence.ping("telegram", "command")                      # the user did something (debounced)
if presence.effect("work.heavy") == "allow": ...         # allow | local | defer
with presence.activity("forge.task", label="Forge", load="heavy", resource="claude_quota"):
    run()                                                  # busy overlay while it runs
presence.signal("resource.claude_quota_left", 12)          # a fact; the engine interprets it
presence.context_line()                                    # "Stato: Sveglio · ultima interazione 2 h fa (telegram)"
```

Chronos down → ``[🔄]`` log and safe defaults (``FALLBACK_EFFECTS``): light and heavy work
allowed (each module still checks its own agenda window), Claude allowed (Forge budget windows
still apply), every notification delivered.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

import requests

logger = logging.getLogger("hestia_common.presence")

FALLBACK_EFFECTS: dict[str, str] = {
    "work.light": "allow", "work.heavy": "allow", "llm.claude": "allow",
    "notify.level": "all", "chat.style": "normal",
}
_CACHE_SECONDS = 15
_FAIL_BACKOFF_SECONDS = 30
_PING_DEBOUNCE_SECONDS = 60


def _hub_default() -> str:
    return os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")


def ago(minutes: float | None) -> str:
    """Italian, short: "adesso", "12 min fa", "3 h fa", "2 giorni fa"."""
    if minutes is None:
        return "mai"
    if minutes < 1:
        return "adesso"
    if minutes < 60:
        return f"{int(minutes)} min fa"
    if minutes < 48 * 60:
        return f"{int(minutes // 60)} h fa"
    return f"{int(minutes // 1440)} giorni fa"


class PresenceClient:
    def __init__(self, module: str, hub_api_url: str | None = None):
        self.module = module
        self.hub = (hub_api_url or _hub_default()).rstrip("/")
        self._lock = threading.Lock()
        self._cache: tuple[float, dict | None] = (0.0, None)
        self._failed_at = 0.0
        self._last_ping: dict[str, float] = {}

    # ── transport ───────────────────────────────────────────────────────────
    def _call(self, method: str, path: str, body: Any = None, timeout: float = 4) -> tuple[int, Any]:
        resp = requests.post(
            f"{self.hub}/route/chronos/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": {}, "body": body, "timeout_seconds": timeout},
            timeout=timeout + 2)
        resp.raise_for_status()
        routed = resp.json() or {}
        if not isinstance(routed, dict):
            raise ValueError("bad Hub answer")
        return int(routed.get("status_code", 500) or 500), routed.get("payload")

    def _send(self, method: str, path: str, body: Any = None, *, background: bool = True) -> None:
        def _go():
            try:
                status, payload = self._call(method, path, body)
                if status >= 400:
                    logger.warning("[🔄] event=presence_call_rejected module=%s path=%s status=%s",
                                   self.module, path, status)
                elif isinstance(payload, dict) and payload.get("base"):
                    with self._lock:
                        self._cache = (time.monotonic(), payload)
            except Exception as exc:
                with self._lock:
                    self._failed_at = time.monotonic()
                logger.warning("[🔄] event=presence_call_failed module=%s path=%s error=%s",
                               self.module, path, exc)
        if background:
            threading.Thread(target=_go, daemon=True, name="presence-send").start()
        else:
            _go()

    # ── reading ─────────────────────────────────────────────────────────────
    def get(self, *, fresh: bool = False) -> dict | None:
        """Current state (cached a few seconds). None when Chronos is unreachable."""
        now = time.monotonic()
        with self._lock:
            at, cached = self._cache
            if cached is not None and not fresh and now - at < _CACHE_SECONDS:
                return cached
            if now - self._failed_at < _FAIL_BACKOFF_SECONDS:
                return cached if cached is not None and now - at < 300 else None
        try:
            status, payload = self._call("GET", "api/presence", timeout=3)
            if status >= 400 or not isinstance(payload, dict) or not payload.get("base"):
                raise ValueError(f"status {status}")
        except Exception as exc:
            with self._lock:
                self._failed_at = now
            logger.warning("[🔄] event=presence_unreachable module=%s error=%s fallback=defaults",
                           self.module, exc)
            return cached if cached is not None and now - at < 300 else None
        with self._lock:
            self._cache = (now, payload)
        return payload

    def effect(self, name: str, default: str | None = None) -> str:
        state = self.get()
        effects = (state or {}).get("effects") or {}
        if name in effects:
            return str(effects[name])
        return default if default is not None else FALLBACK_EFFECTS.get(name, "allow")

    def allows(self, name: str, *accepted: str) -> bool:
        """``allows("work.heavy")`` → allow only; ``allows("work.heavy", "allow", "local")`` for local jobs."""
        return self.effect(name) in (accepted or ("allow",))

    def context_line(self, state: dict | None = None) -> str:
        """One short line for a model's context (empty when unknown)."""
        state = state if state is not None else self.get()
        if not state:
            return ""
        parts = [f"Stato assistente: {state.get('label') or state.get('base')}"]
        if state.get("last_interaction_at"):
            client = state.get("last_interaction_client") or ""
            parts.append(f"ultima interazione {ago(state.get('idle_minutes'))}" + (f" ({client})" if client else ""))
        else:
            parts.append("nessuna interazione registrata")
        notice = (state.get("effects") or {}).get("chat.notice")
        if notice:
            parts.append(f"avvisa se utile: {notice}")
        return " · ".join(parts)

    # ── reporting ───────────────────────────────────────────────────────────
    def ping(self, client: str, kind: str = "chat", *, force: bool = False) -> None:
        """The user interacted (debounced per client+kind, background)."""
        key = f"{client}:{kind}"
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_ping.get(key, -1e9) < _PING_DEBOUNCE_SECONDS:
                return
            self._last_ping[key] = now
        self._send("POST", "api/presence/ping", {"client": client, "kind": kind})

    def activity_start(self, key: str, *, label: str = "", load: str = "light", resource: str = "",
                       kind: str = "work", ttl_seconds: float = 3600, background: bool = True) -> None:
        self._send("POST", "api/presence/activity", {
            "key": key, "label": label, "load": load, "resource": resource, "kind": kind,
            "module": self.module, "ttl_seconds": ttl_seconds}, background=background)

    def activity_stop(self, key: str, *, background: bool = True) -> None:
        self._send("DELETE", f"api/presence/activity/{key}", background=background)

    @contextmanager
    def activity(self, key: str, **kwargs: Any) -> Iterator[None]:
        """Report an activity for the duration of a block (never raises because of presence).
        The start is sent inline (so the stop can't overtake it) unless Chronos just failed."""
        recently_failed = time.monotonic() - self._failed_at < _FAIL_BACKOFF_SECONDS
        kwargs.setdefault("background", recently_failed)
        self.activity_start(key, **kwargs)
        try:
            yield
        finally:
            self.activity_stop(key)

    def signal(self, key: str, value: Any = True, *, meta: dict | None = None,
               ttl_seconds: float | None = None) -> None:
        self._send("PUT", f"api/presence/signals/{key}",
                   {"value": value, "meta": meta or {"module": self.module}, "ttl_seconds": ttl_seconds})

    def clear(self, key: str) -> None:
        self._send("DELETE", f"api/presence/signals/{key}")

    def declare_states(self, states: dict[str, dict]) -> None:
        """Module-specific states (same format as ``chronos.presence.states``); re-assert hourly."""
        self._send("POST", "api/presence/states/register", {"owner": self.module, "states": states})


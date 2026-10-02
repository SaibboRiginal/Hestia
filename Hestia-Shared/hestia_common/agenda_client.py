"""Assistant agenda client — every module plans in Hestia's own calendar (Chronos).

The assistant agenda (Chronos ``/api/agenda*``, source ``hestia``) is where
modules declare *when* they work, as data the user can see and change:

- ``job``    recurring action fired by Chronos through Hub (e.g. Scout cycle);
- ``window`` period in which a module is allowed to work (Athena consolidation,
             Metis training, Claude Pro nights); the module asks ``is_open``;
- ``task``   one-off action at a given time (repairs, scheduled trainings);
- ``event``  informational entry (what a module plans to do).

Rules are registered idempotently by ``key``: user edits (move, skip, cancel)
are never overwritten by the module. Chronos unreachable → every helper fails
soft and ``is_open`` uses the caller's fallback, so modules keep working.

All calls go through Hub (``/route/chronos/...``) — no direct service links.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import requests

logger = logging.getLogger("hestia_common.agenda")


def _hub_default() -> str:
    return os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")


def job_rule(key: str, title: str, *, service: str, path: str, recurrence: str,
             start_at: str = "2026-01-01T00:00:00", method: str = "POST", body: dict | None = None,
             description: str = "", params: dict | None = None, tz: str | None = None,
             timeout_seconds: float = 60) -> dict:
    """Build a recurring ``job`` rule whose action Chronos fires through Hub."""
    rule = {"key": key, "type": "job", "title": title, "description": description,
            "start_at": start_at, "recurrence": recurrence,
            "action": {"service": service, "path": path, "method": method, "body": body,
                       "timeout_seconds": timeout_seconds},
            "params": params or {}}
    if tz:
        rule["tz"] = tz
    return rule


def window_rule(key: str, title: str, *, start_at: str, end_at: str, recurrence: str,
                description: str = "", params: dict | None = None, tz: str | None = None) -> dict:
    """Build a recurring ``window`` rule (each occurrence lasts end_at - start_at)."""
    rule = {"key": key, "type": "window", "title": title, "description": description,
            "start_at": start_at, "end_at": end_at, "recurrence": recurrence, "params": params or {}}
    if tz:
        rule["tz"] = tz
    return rule


def daily_window(key: str, title: str, start_hour: int, end_hour: int, *, description: str = "",
                 params: dict | None = None, tz: str | None = None) -> dict:
    """Every day from ``start_hour`` to ``end_hour`` local time (crosses midnight if end <= start)."""
    start_hour, end_hour = int(start_hour) % 24, int(end_hour) % 24
    length = (end_hour - start_hour) % 24 or 24
    start = datetime(2026, 1, 1, start_hour)
    end_day = 1 + (start_hour + length) // 24
    end = datetime(2026, 1, end_day, (start_hour + length) % 24)
    return window_rule(key, title, start_at=start.isoformat(), end_at=end.isoformat(),
                       recurrence="FREQ=DAILY", description=description, params=params, tz=tz)


class AgendaClient:
    """Thin Hub client for the assistant agenda, bound to one owner module."""

    def __init__(self, owner: str, hub_api_url: str | None = None):
        self.owner = owner
        self.hub = (hub_api_url or _hub_default()).rstrip("/")

    # ── transport ───────────────────────────────────────────────────────────
    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None,
              timeout: float = 10) -> tuple[int, Any]:
        resp = requests.post(
            f"{self.hub}/route/chronos/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": query or {}, "body": body,
                  "timeout_seconds": timeout},
            timeout=timeout + 3)
        resp.raise_for_status()
        routed = resp.json() or {}
        return int(routed.get("status_code", 500)), routed.get("payload")

    def _safe(self, event: str, method: str, path: str, **kw) -> tuple[int, Any]:
        try:
            return self._call(method, path, **kw)
        except Exception as exc:
            logger.warning("[🔄] event=%s owner=%s error=%s", event, self.owner, exc)
            return 0, None

    # ── rules ───────────────────────────────────────────────────────────────
    def register(self, rules: list[dict]) -> bool:
        """Declare module defaults (idempotent by key; user edits win)."""
        if not rules:
            return True
        status, _ = self._safe("agenda_register_failed", "POST", "api/agenda/register",
                               body={"owner": self.owner, "rules": rules})
        if status and status < 400:
            logger.info("event=agenda_registered owner=%s rules=%d", self.owner, len(rules))
            return True
        return False

    def register_async(self, rules: list[dict] | Callable[[], list[dict]], *, retry_seconds: float = 60,
                       refresh_seconds: float = 3600) -> threading.Thread:
        """Register in background: retry until Chronos answers, then re-assert hourly
        (idempotent; user edits are preserved by Chronos)."""
        def _loop():
            import time
            while True:
                ok = self.register(rules() if callable(rules) else rules)
                time.sleep(refresh_seconds if ok else retry_seconds)

        thread = threading.Thread(target=_loop, daemon=True, name=f"agenda-register-{self.owner}")
        thread.start()
        return thread

    def lookup(self, key: str) -> tuple[bool, dict | None]:
        """``(reachable, item)`` — distinguishes 'Chronos down' from 'item missing'."""
        status, payload = self._safe("agenda_lookup_failed", "GET", "api/agenda/items",
                                     query={"include_cancelled": True, "owner": self.owner}, timeout=6)
        if not status or status >= 400 or not isinstance(payload, dict):
            return False, None
        return True, next((i for i in payload.get("items", []) if i.get("key") == key), None)

    def should_self_run(self, key: str, interval_seconds: float, stale_factor: float = 3) -> bool:
        """Fallback guard for a recurring ``job`` the agenda should fire.

        True (run it yourself) when Chronos is unreachable, the job is missing,
        or it is active but has not fired for ``stale_factor`` × interval.
        False when the agenda is handling it — or the user paused/cancelled it
        (a decision, not a failure).
        """
        reachable, item = self.lookup(key)
        if not reachable or item is None:
            return True
        if item.get("status") in {"paused", "cancelled", "completed"}:
            return False
        last = item.get("last_fired")
        if not last:
            return False  # just registered: the agenda fires it at the next occurrence
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                   ).total_seconds()
        except ValueError:
            return True
        return age > stale_factor * interval_seconds

    def window(self, key: str) -> dict | None:
        """Window status ``{exists, active, until, next_open, params}``; None if Chronos is down."""
        status, payload = self._safe("agenda_window_unreachable", "GET", f"api/agenda/windows/{key}",
                                     timeout=6)
        return payload if status and status < 400 and isinstance(payload, dict) else None

    def is_open(self, key: str, fallback: Callable[[], bool]) -> bool:
        """Is window ``key`` open now? Agenda wins; missing window or Chronos down → ``fallback()``.

        A window the user cancelled or skipped is *closed* (no fallback): that is a decision.
        """
        st = self.window(key)
        if st is None or not st.get("exists"):
            return bool(fallback())
        return bool(st.get("active"))

    # ── one-off items ───────────────────────────────────────────────────────
    def plan(self, key: str, title: str, start_at: str | datetime, *, type_: str = "task",
             end_at: str | datetime | None = None, action: dict | None = None,
             description: str = "", params: dict | None = None) -> dict | None:
        """Create/refresh a one-off ``task`` (with action) or ``event`` (informational)."""
        def iso(v):
            if isinstance(v, datetime):
                return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
            return v
        body = {"key": key, "type": type_, "owner": self.owner, "created_by": self.owner,
                "title": title[:200], "description": (description or "")[:1000],
                "start_at": iso(start_at), "end_at": iso(end_at), "action": action,
                "params": params or {}}
        status, payload = self._safe("agenda_plan_failed", "POST", "api/agenda/items", body=body)
        if status and status < 400 and isinstance(payload, dict):
            return payload.get("item")
        return None

    def show(self, key: str, title: str, start_at: str | datetime, description: str = "",
             end_at: str | datetime | None = None, params: dict | None = None) -> dict | None:
        """Informational event (what the module plans to do), visible to the user."""
        return self.plan(key, title, start_at, type_="event", end_at=end_at,
                         description=description, params=params)

    def update(self, key: str, **changes) -> dict | None:
        status, payload = self._safe("agenda_update_failed", "PATCH", f"api/agenda/items/{key}",
                                     body={**changes, "by": self.owner})
        return payload.get("item") if status and status < 400 and isinstance(payload, dict) else None

    def done(self, key: str) -> None:
        """Mark a one-off as completed (keeps history, hides it from the agenda)."""
        self.update(key, status="completed")

    def cancel(self, key: str) -> None:
        self._safe("agenda_cancel_failed", "DELETE", f"api/agenda/items/{key}", query={"by": self.owner})

    def get(self, key: str) -> dict | None:
        items = self.items(include_cancelled=True, owner=None)
        return next((i for i in items if i.get("key") == key), None)

    # ── reading (modules see each other's plans) ───────────────────────────
    def items(self, owner: str | None = "", type_: str | None = None,
              include_cancelled: bool = False) -> list[dict]:
        """Items of ``owner`` (default: self; ``None`` = every module)."""
        query: dict[str, Any] = {"include_cancelled": include_cancelled}
        who = self.owner if owner == "" else owner
        if who:
            query["owner"] = who
        if type_:
            query["type"] = type_
        status, payload = self._safe("agenda_items_failed", "GET", "api/agenda/items", query=query)
        return payload.get("items", []) if status and status < 400 and isinstance(payload, dict) else []

    def agenda(self, days: int = 7, owner: str | None = None, type_: str | None = None) -> list[dict]:
        """Upcoming occurrences of every module (or one ``owner``)."""
        query: dict[str, Any] = {"days": days}
        if owner:
            query["owner"] = owner
        if type_:
            query["type"] = type_
        status, payload = self._safe("agenda_view_failed", "GET", "api/agenda", query=query)
        return payload.get("occurrences", []) if status and status < 400 and isinstance(payload, dict) else []

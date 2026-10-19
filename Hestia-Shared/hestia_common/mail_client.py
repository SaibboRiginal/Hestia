"""Mail subscriptions — modules get their emails by PUSH from Iris, never by polling the mailbox.

One watcher (Hecate) sees every new Gmail message and hands the headers to Iris. Iris matches them
against the subscriptions declared here; for each match it ships the full mail to Archive as a raw
record under the subscriber's ``domain`` (durable, deduplicated) and then calls the subscriber's
``path`` through Hub with ``{owner, key, domain, count, reference_ids}`` ("the doorbell").

A module therefore:
1. declares rules at boot with ``MailClient(owner).subscribe_async(rules)`` (idempotent by key,
   re-asserted hourly, rebuild them when its own settings change);
2. exposes ``path`` (POST) that processes its pending raw records
   (Archive ``GET /api/archive/<domain>/unevaluated``) — also called once at startup, so mails that
   arrived while it was down are not lost;
3. may ask for a backfill (``backfill(key)``) for a "check now" button.

All calls go through Hub (``/route/iris/...``). Iris unreachable → fail soft, retried.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

import requests

logger = logging.getLogger("hestia_common.mail")


def _hub_default() -> str:
    return os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [str(v).strip() for v in value if str(v).strip()]


def mail_rule(key: str, title: str, *, path: str, domain: str, senders: Any = None,
              subject_contains: Any = None, labels: Any = None, queries: Any = None,
              description: str = "", backfill_days: int | None = None) -> dict:
    """Build a subscription rule.

    Matching (deterministic, on headers): ``senders`` = addresses (``a@b.it``) or domains (``b.it`` /
    ``@b.it``); ``subject_contains`` = words (any); ``labels`` = Gmail label ids (any). Filled groups are
    AND-ed, values inside a group are OR-ed. ``queries`` = Gmail/IMAP searches evaluated by Hecate
    (a mail matches if any query returns it) — for rules the header match cannot express.
    """
    rule = {"key": key, "title": title, "path": path, "domain": domain,
            "senders": _as_list(senders), "subject_contains": _as_list(subject_contains),
            "labels": _as_list(labels), "queries": [q for q in (queries or []) if str(q).strip()]
            if not isinstance(queries, str) else [q.strip() for q in queries.split("||") if q.strip()],
            "description": description}
    if backfill_days is not None:
        rule["backfill_days"] = int(backfill_days)
    return rule


class MailClient:
    """Thin Hub client for Iris subscriptions, bound to one owner module."""

    def __init__(self, owner: str, hub_api_url: str | None = None):
        self.owner = owner
        self.hub = (hub_api_url or _hub_default()).rstrip("/")
        self._rules: list[dict] | Callable[[], list[dict]] = []
        self._wake = threading.Event()

    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None,
              timeout: float = 15) -> tuple[int, Any]:
        resp = requests.post(
            f"{self.hub}/route/iris/{path.lstrip('/')}",
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

    def subscribe(self, rules: list[dict]) -> bool:
        """Declare the module's full rule set (idempotent; keys no longer listed are removed)."""
        status, payload = self._safe("mail_subscribe_failed", "POST", "api/email/subscriptions",
                                     body={"owner": self.owner, "rules": list(rules)})
        if status and status < 400:
            logger.info("event=mail_subscribed owner=%s rules=%d backfill=%s", self.owner, len(rules),
                        (payload or {}).get("backfill") if isinstance(payload, dict) else None)
            return True
        return False

    def subscribe_async(self, rules: list[dict] | Callable[[], list[dict]], *, retry_seconds: float = 60,
                        refresh_seconds: float = 3600) -> threading.Thread:
        """Subscribe in background: retry until Iris answers, then re-assert hourly. ``refresh()`` re-sends
        at once (call it when the settings behind the rules change)."""
        self._rules = rules

        def _loop():
            while True:
                current = self._rules() if callable(self._rules) else self._rules
                ok = self.subscribe(current)
                self._wake.wait(refresh_seconds if ok else retry_seconds)
                self._wake.clear()

        thread = threading.Thread(target=_loop, daemon=True, name=f"mail-subscribe-{self.owner}")
        thread.start()
        return thread

    def refresh(self) -> None:
        self._wake.set()

    def backfill(self, key: str, days: int | None = None) -> dict:
        """Ask Iris to deliver matching mails of the last ``days`` (the module's "check now")."""
        status, payload = self._safe("mail_backfill_failed", "POST",
                                     f"api/email/subscriptions/{self.owner}/{key}/backfill",
                                     body={"days": days} if days else {}, timeout=110)
        if status and status < 400 and isinstance(payload, dict):
            return payload
        return {"status": "error", "error": payload if status else "iris unreachable"}

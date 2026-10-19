"""Mail watcher — the ONE place that looks at the mailbox for new mail (SPEC docs/work/2026-10-19-email-push-spese).

Light check: Gmail history API from the last ``historyId`` (one tiny call with an empty answer when nothing
arrived; no search, no body). New messages → headers only → Iris ``/api/email/incoming`` (via Hub), which
decides who gets what. The cursor advances only after Iris accepted the batch, so nothing is lost when Iris is
down. History expired (Gmail keeps about a week) → ``[🔄]`` search since the last check.

Triggers: the agenda job ``hecate.mail_watch`` (Chronos) and, when configured, Gmail push via Pub/Sub
(``core.gmail_pubsub``), which just calls ``run('pubsub')``.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from providers.google import GmailHistoryExpired, GoogleMailAuthError

logger = logging.getLogger("hestia_hecate.mail_watch")

_HEADER_FIELDS = ("id", "message_id", "thread_id", "subject", "from", "to", "date", "created_at", "snippet",
                  "labels")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MailWatcher:
    def __init__(self, state_file: str | Path, gateway: Any, push: Callable[[list[dict], str], bool]):
        self.state_file = Path(state_file)
        self.gateway = gateway
        self.push = push
        self._lock = threading.Lock()
        self._again = threading.Event()
        self.state: dict[str, Any] = self._load()

    # ── state ────────────────────────────────────────────────────────────────
    def _load(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[🔄] event=mail_watch_state_save_failed error=%s", exc)

    def status(self) -> dict:
        return {k: self.state.get(k) for k in ("history_id", "last_check", "last_ok", "last_new", "last_source",
                                               "last_trigger", "last_error", "pushed_total", "pending")}

    # ── run ──────────────────────────────────────────────────────────────────
    def run(self, trigger: str = "agenda") -> dict:
        """One check. Concurrent triggers (agenda + push) collapse: the running check runs once more."""
        if not self._lock.acquire(blocking=False):
            self._again.set()
            return {"status": "busy"}
        try:
            out = self._run_once(trigger)
            while self._again.is_set():
                self._again.clear()
                out = self._run_once(trigger)
            return out
        finally:
            self._lock.release()

    def _run_once(self, trigger: str) -> dict:
        started = _now()
        self.state.update(last_check=started.isoformat(), last_trigger=trigger)
        gmail = self.gateway.gmail()
        if not gmail.is_available():
            self.state["last_error"] = "gmail_not_authorized"
            self._save()
            logger.warning("[🔄] event=mail_watch_skipped reason=gmail_not_authorized trigger=%s", trigger)
            return {"status": "skipped", "reason": "gmail_not_authorized", "action_required": "reauth_google"}
        try:
            history_id = self.state.get("history_id")
            if not history_id:
                self.state.update(history_id=gmail.current_history_id(), last_ok=started.isoformat(),
                                  last_error=None, last_new=0)
                self._save()
                logger.info("event=mail_watch_initialized history_id=%s", self.state["history_id"])
                return {"status": "initialized", "new": 0}
            source = "history"
            try:
                ids, latest = gmail.added_since(history_id)
            except GmailHistoryExpired:
                since = self.state.get("last_ok") or (started - timedelta(days=1)).isoformat()
                since_dt = datetime.fromisoformat(since)
                rows = gmail.list_messages(q="-in:sent -in:drafts", since=since_dt - timedelta(minutes=5),
                                           limit=200, full=False)
                ids, latest, source = [r["id"] for r in rows], gmail.current_history_id(), "fallback"
                logger.warning("[🔄] event=mail_watch_history_expired since=%s found=%d", since, len(ids))
            ids = list(dict.fromkeys((self.state.get("pending") or []) + ids))
            headers = []
            for mid in ids:
                row = gmail.headers(mid)
                if row:
                    headers.append({k: row.get(k) for k in _HEADER_FIELDS})
            if headers and not self.push(headers, source):
                # keep the cursor: the same mails are offered again at the next check
                self.state.update(pending=ids, last_error="iris_unreachable")
                self._save()
                logger.warning("[🔄] event=mail_watch_push_failed new=%d cursor_kept=%s", len(headers), history_id)
                return {"status": "error", "error": "iris_unreachable", "new": len(headers)}
            self.state.update(history_id=latest, last_ok=started.isoformat(), last_error=None,
                              last_new=len(headers), last_source=source, pending=[],
                              pushed_total=int(self.state.get("pushed_total") or 0) + len(headers))
            self._save()
            if headers:
                logger.info("event=mail_watch_pushed new=%d source=%s trigger=%s", len(headers), source, trigger)
            return {"status": "ok", "new": len(headers), "source": source}
        except GoogleMailAuthError as exc:
            self.gateway.reset()
            self.state["last_error"] = str(exc)[:300]
            self._save()
            logger.warning("[🔄] event=mail_watch_auth_failed error=%s", exc)
            return {"status": "skipped", "reason": "gmail_auth", "action_required": "reauth_google"}
        except Exception as exc:
            self.state["last_error"] = str(exc)[:300]
            self._save()
            logger.warning("[🔄] event=mail_watch_failed error=%s", exc)
            return {"status": "error", "error": str(exc)[:300]}

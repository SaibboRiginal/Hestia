"""Gmail push through Google Cloud Pub/Sub — optional, inactive until configured.

Gmail can push only through Pub/Sub. Hecate uses **streaming pull**: one outgoing connection stays open
and Pub/Sub delivers notifications on it as they happen, so it is real push **without a public URL**
(the quick tunnel URL changes at every restart). Each notification only says "the mailbox changed":
Hecate then runs the normal watcher (history API), which stays the single source of truth.

Configuration (infrastructure, env — one-time setup in Marko's Google Cloud project, see hestia-hecate.md):
- ``HECATE_GMAIL_PUBSUB_TOPIC``         projects/<project>/topics/<topic> (publisher: gmail-api-push@system.gserviceaccount.com)
- ``HECATE_GMAIL_PUBSUB_SUBSCRIPTION``  projects/<project>/subscriptions/<sub> (pull)
- ``HECATE_GMAIL_PUBSUB_CREDENTIALS``   service account JSON with only "Pub/Sub Subscriber" (default data/gmail-pubsub-sa.json)
``users.watch`` expires after 7 days: the agenda job ``hecate.mail_watch_renew`` renews it daily.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("hestia_hecate.gmail_pubsub")


def topic() -> str:
    return os.getenv("HECATE_GMAIL_PUBSUB_TOPIC", "").strip()


def subscription() -> str:
    return os.getenv("HECATE_GMAIL_PUBSUB_SUBSCRIPTION", "").strip()


def credentials_file() -> str:
    return os.getenv("HECATE_GMAIL_PUBSUB_CREDENTIALS", "/code/data/gmail-pubsub-sa.json").strip()


def configured() -> bool:
    return bool(topic() and subscription())


class PubSubListener:
    """Keeps one streaming pull open; every message → ``on_change()`` (debounced by the watcher lock)."""

    def __init__(self, on_change: Callable[[], Any]):
        self.on_change = on_change
        self.state: dict[str, Any] = {"configured": configured(), "active": False, "last_message_at": None,
                                      "messages": 0, "error": None, "watch_expiration": None,
                                      "watch_renewed_at": None}
        self._thread: threading.Thread | None = None

    def status(self) -> dict:
        return {**self.state, "configured": configured(), "topic": topic() or None}

    def start(self) -> bool:
        if not configured():
            logger.info("event=gmail_pubsub_inactive reason=not_configured")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gmail-pubsub")
        self._thread.start()
        return True

    def _callback(self, message) -> None:
        try:
            message.ack()
        finally:
            self.state.update(last_message_at=datetime.now(timezone.utc).isoformat(),
                              messages=int(self.state["messages"]) + 1)
            threading.Thread(target=self.on_change, daemon=True, name="gmail-pubsub-run").start()

    def _loop(self) -> None:
        backoff = 30
        while True:
            try:
                from google.cloud import pubsub_v1  # optional dependency, imported only when configured
                from google.oauth2 import service_account

                creds = service_account.Credentials.from_service_account_file(
                    credentials_file(), scopes=["https://www.googleapis.com/auth/pubsub"])
                subscriber = pubsub_v1.SubscriberClient(credentials=creds)
                future = subscriber.subscribe(subscription(), callback=self._callback)
                self.state.update(active=True, error=None)
                logger.info("event=gmail_pubsub_listening subscription=%s", subscription())
                backoff = 30
                future.result()          # blocks while the stream is open
            except Exception as exc:
                self.state.update(active=False, error=str(exc)[:300])
                logger.warning("[🔄] event=gmail_pubsub_stream_failed error=%s retry_in=%ss", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 1800)

    def renew(self, gmail) -> dict:
        """(Re)start Gmail notifications on the topic; returns Gmail's ``{historyId, expiration}``."""
        if not configured():
            return {"status": "inactive", "reason": "not_configured"}
        try:
            out = gmail.watch(topic())
        except Exception as exc:
            self.state["error"] = str(exc)[:300]
            logger.warning("[🔄] event=gmail_watch_renew_failed error=%s", exc)
            return {"status": "error", "error": str(exc)[:300]}
        exp = out.get("expiration")
        self.state.update(watch_renewed_at=datetime.now(timezone.utc).isoformat(),
                          watch_expiration=datetime.fromtimestamp(int(exp) / 1000, tz=timezone.utc).isoformat()
                          if exp else None)
        logger.info("event=gmail_watch_renewed expiration=%s", self.state["watch_expiration"])
        return {"status": "ok", **self.state}

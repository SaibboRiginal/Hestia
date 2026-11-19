"""The message she wrote first stays in the conversation (docs/work/2026-11-16-name-everywhere).

Athena decides to write, Oracle writes it, Hermes delivers it (kind ``athena.talk``): it lives in Hermes, not in a
conversation. When the owner then writes, on any client and on any later day, his first turn after that message
takes it in: the message is saved in *that* conversation as an assistant message, with the time she wrote it,
before his. So his answer has its context in the history the model reads, and the chat shows it when reopened.

Once only: it is taken in when no conversation has been written after it (so the first turn after it wins) and
it is not already in this conversation. Messages older than ``MAX_DAYS`` are left alone. Any failure skips it
(``[🔄]`` log): a turn never waits on this.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger(f"hestia_oracle.{__name__}")

TALK_KIND = "athena.talk"
MAX_DAYS = 3
TIMEOUT_SECONDS = 3

Route = Callable[..., Any]       # (method, endpoint, body=None, query=None) → Archive payload or None


def _at(value: Any) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def latest_opener(payload: Any, now: datetime | None = None) -> dict | None:
    """``{"text", "at"}`` of the newest message she wrote first within ``MAX_DAYS``, from Hermes notifications."""
    items = (payload or {}).get("items") if isinstance(payload, dict) else None
    now = now or datetime.now(timezone.utc)
    best = None
    for row in items or []:
        if not isinstance(row, dict) or row.get("kind") != TALK_KIND:
            continue
        at, text = _at(row.get("created_at")), str(row.get("message") or "").strip()
        if not at or not text or now - at > timedelta(days=MAX_DAYS):
            continue
        if best is None or at > best["at"]:
            best = {"text": text, "at": at}
    return best


def written_after(sessions: Any, at: datetime) -> bool:
    """True when any conversation has a message after ``at`` (someone already answered or chatted since)."""
    items = sessions.get("items") if isinstance(sessions, dict) else None
    for item in items or []:
        last = _at((item or {}).get("last_at"))
        if last and last > at:
            return True
    return False


def absorb(hub, route: Route, session_id: str, now: datetime | None = None) -> bool:
    """Save the latest opener in ``session_id`` before the owner's message, once. Returns True when saved."""
    if not session_id:
        return False
    try:
        ok, payload = hub.route_to_service("hermes", "api/notifications", "GET", query={"limit": 20},
                                           timeout=TIMEOUT_SECONDS)
        opener = latest_opener(payload if ok else None, now)
        if not opener:
            return False
        sessions = route("GET", "/chat/sessions/list", query={"limit": 100})
        if sessions is None:          # cannot tell whether it was already taken in: never save it twice
            logger.info("[🔄] event=opener_history_sessions_unavailable fallback=awareness_line")
            return False
        if written_after(sessions, opener["at"]):
            return False
        history = route("GET", f"/chat/history/{session_id}", query={"limit": 20}) or []
        if any(str((m or {}).get("content") or "").strip() == opener["text"] for m in history):
            return False
        saved = route("POST", "/chat/history", body={"session_id": session_id, "role": "assistant",
                                                     "content": opener["text"],
                                                     "timestamp": opener["at"].isoformat()})
        if saved is None:
            logger.warning("[🔄] event=opener_history_not_saved session_id=%s fallback=awareness_line", session_id)
            return False
    except Exception as exc:  # noqa: BLE001 - the awareness line still tells her what she wrote today
        logger.warning("[🔄] event=opener_history_failed session_id=%s error=%s fallback=awareness_line",
                       session_id, str(exc)[:160])
        return False
    logger.info("event=opener_history_saved session_id=%s chars=%d", session_id, len(opener["text"]))
    return True

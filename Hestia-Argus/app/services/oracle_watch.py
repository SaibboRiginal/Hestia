"""Oracle watch — Oracle (the only LLM core) down for longer than ``argus.oracle.grace``.

SPEC docs/work/2026-10-19-oracle-offline §1. Fed by the monitor cycle (no loop of its own):
- offline → presence signal ``oracle.offline`` (Chronos overlay «Non disponibile», effect ``chat.reply=queued``;
  when it relaxes Chronos asks the chat clients to answer their queues) + one Hermes notice with fixed text
  (``replaces: system.oracle``, one live notice);
- back → signal cleared + the notice closed with «di nuovo online».
While offline Argus never asks Oracle to narrate (fixed texts at once). A shorter outage (restart, deploy) says
nothing: chat clients queue their messages anyway.

v3 E — Oracle's ``/health`` also says how it can answer (``models``): ``none`` (no model usable: Oracle refuses chats
with 503, clients queue) counts as offline; ``limited`` (only fallback models) for longer than the same grace →
presence signal ``oracle.limited`` (Chronos overlay «Limitato») + one notice on the same key; back to ``ok`` → cleared.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from core import argus_settings as cfg
from core import hermes_client

logger = logging.getLogger(f"hestia_argus.{__name__}")

ORACLE = "oracle"
SIGNAL = "oracle.offline"
SIGNAL_LIMITED = "oracle.limited"
NOTICE_KEY = "system.oracle"
# The system subscription Hermes bootstraps for the user on every client (service.health alerts are opt-in):
# the Oracle notice must always arrive.
NOTICE_EVENT = "service.action_required"
_REFRESH_SECONDS = 600     # re-send the signal so its TTL never lapses while offline
_SIGNAL_TTL = 1800         # a dead Argus does not leave the overlay on forever

_lock = threading.Lock()
_state: dict = {"failing_since": None, "offline": False, "offline_since": None, "signal_at": 0.0, "reason": "",
               "limited_since": None, "limited": False, "limited_signal_at": 0.0}

try:
    from hestia_common.presence_client import PresenceClient
    from core import hub_client
    _presence = PresenceClient("argus", hub_client.HUB_API_URL)
except ModuleNotFoundError:  # local run without the shared package on sys.path
    _presence = None


def is_offline() -> bool:
    with _lock:
        return bool(_state["offline"])


def snapshot() -> dict:
    with _lock:
        since = _state["offline_since"]
        return {"offline": bool(_state["offline"]), "reason": _state["reason"],
                "since": datetime.fromtimestamp(since, tz=timezone.utc).isoformat() if since else None}


def _minutes(seconds: float) -> str:
    minutes = max(1, int(round(seconds / 60)))
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h {minutes % 60} min"


def _signal(since: float, reason: str) -> None:
    if _presence is None:
        return
    _presence.signal(SIGNAL, True, meta={"module": "argus", "reason": reason,
                                         "since": datetime.fromtimestamp(since, tz=timezone.utc).isoformat()},
                     ttl_seconds=_SIGNAL_TTL)


def observe(status: str | None, error: str | None = None, *, now: float | None = None,
            models: str | None = None) -> str | None:
    """One Oracle health observation (``None`` = not registered on Hub; ``models`` from its ``/health``).
    Returns ``"offline"``/``"online"``/``"limited"``/``"full"`` on a transition, else ``None``."""
    now = time.time() if now is None else now
    if status == "up" and models == "none":
        status, error = "no_models", error or "no model can answer"
    healthy = status == "up"
    reason = "unregistered" if status is None else ("unreachable" if status == "down" else
                                                    "no_models" if status == "no_models" else "unhealthy")
    transition = None
    with _lock:
        if healthy:
            was_offline, since = _state["offline"], _state["offline_since"]
            _state.update(failing_since=None, offline=False, offline_since=None, signal_at=0.0, reason="")
            if was_offline:
                transition = "online"
        else:
            if _state["failing_since"] is None:
                _state["failing_since"] = now
            failing_since = _state["failing_since"]
            _state["reason"] = reason
            if not _state["offline"] and now - failing_since >= cfg.get_int(cfg.ORACLE_GRACE, 0):
                _state.update(offline=True, offline_since=failing_since, signal_at=now)
                transition = "offline"
            elif _state["offline"] and now - _state["signal_at"] >= _REFRESH_SECONDS:
                _state["signal_at"] = now
                _signal(failing_since, reason)
    if transition == "offline":
        _end_limited(now, notify=False)
        _go_offline(failing_since, reason, error)
    elif transition == "online":
        _go_online(now - (since or now))
    if healthy:
        limited = _observe_limited(models == "limited", now)
        transition = transition or limited
    return transition


def _observe_limited(limited: bool, now: float) -> str | None:
    """Only fallback models answer (v3 E): «Limitato» after the grace, cleared when the first model is back."""
    with _lock:
        if not limited:
            was = _state["limited"]
            _state.update(limited_since=None, limited=False, limited_signal_at=0.0)
        else:
            if _state["limited_since"] is None:
                _state["limited_since"] = now
            since = _state["limited_since"]
            if not _state["limited"] and now - since >= cfg.get_int(cfg.ORACLE_GRACE, 0):
                _state.update(limited=True, limited_signal_at=now)
                start = True
            else:
                start = False
                if _state["limited"] and now - _state["limited_signal_at"] >= _REFRESH_SECONDS:
                    _state["limited_signal_at"] = now
                    _limited_signal(since)
    if not limited:
        if was:
            _end_limited(now, notify=True)
            return "full"
        return None
    if start:
        logger.warning("[🔄] event=oracle_limited since=%s", int(since))
        _limited_signal(since)
        hermes_client.publish_event(
            domain="system", event_type=NOTICE_EVENT, entity_id=f"{NOTICE_KEY}.limited",
            payload={"_message": "🔋 <b>Limitato</b>: rispondo, ma in modo ridotto finché i modelli principali non "
                                 "tornano disponibili. I lavori pesanti aspettano.",
                     "_title": "Limitato", "_level": "warning", "_source": "argus",
                     "replaces": NOTICE_KEY, "service": ORACLE, "status": "oracle_limited"})
        return "limited"
    return None


def _limited_signal(since: float) -> None:
    if _presence is None:
        return
    _presence.signal(SIGNAL_LIMITED, True, meta={"module": "argus", "since": datetime.fromtimestamp(
        since, tz=timezone.utc).isoformat()}, ttl_seconds=_SIGNAL_TTL)


def _end_limited(now: float, notify: bool) -> None:
    """Leave «Limitato» (back to full, or worse: offline takes over the same notice)."""
    with _lock:
        was = _state["limited"]
        _state.update(limited_since=None, limited=False, limited_signal_at=0.0)
    if _presence is not None and (was or notify):
        _presence.clear(SIGNAL_LIMITED)
    if notify:
        logger.info("event=oracle_full")
        hermes_client.publish_event(
            domain="system", event_type=NOTICE_EVENT, entity_id=f"{NOTICE_KEY}.full",
            payload={"_message": "✅ <b>Di nuovo al completo</b>: rispondo di nuovo come sempre.",
                     "_title": "Di nuovo al completo", "_level": "success", "_source": "argus",
                     "closes": NOTICE_KEY, "decision": "resolved", "outcome_text": "Di nuovo al completo",
                     "service": ORACLE, "status": "oracle_full"})


def _go_offline(since: float, reason: str, error: str | None) -> None:
    logger.warning("[🔄] event=oracle_offline reason=%s error=%s", reason, str(error or "")[:200])
    _signal(since, reason)
    hermes_client.publish_event(
        domain="system", event_type=NOTICE_EVENT, entity_id=NOTICE_KEY,
        payload={"_message": "⏳ <b>Non disponibile</b>: non posso rispondere adesso. Comandi, notifiche e agenda "
                             "funzionano; i messaggi in chat restano in coda e avranno risposta appena possibile.",
                 "_title": "Non disponibile", "_level": "warning", "_source": "argus",
                 "replaces": NOTICE_KEY, "service": ORACLE, "status": "oracle_offline", "reason": reason})


def _go_online(seconds_offline: float) -> None:
    logger.info("event=oracle_online offline_for_s=%d", int(seconds_offline))
    if _presence is not None:
        _presence.clear(SIGNAL)
    hermes_client.publish_event(
        domain="system", event_type=NOTICE_EVENT, entity_id=f"{NOTICE_KEY}.online",
        payload={"_message": f"✅ <b>Di nuovo disponibile</b> dopo {_minutes(seconds_offline)}: rispondo ai messaggi "
                             "rimasti in coda.",
                 "_title": "Di nuovo disponibile", "_level": "success", "_source": "argus",
                 "closes": NOTICE_KEY, "decision": "resolved", "outcome_text": "Di nuovo disponibile",
                 "service": ORACLE, "status": "oracle_online"})


def reset() -> None:
    """Tests only."""
    with _lock:
        _state.update(failing_since=None, offline=False, offline_since=None, signal_at=0.0, reason="",
                      limited_since=None, limited=False, limited_signal_at=0.0)

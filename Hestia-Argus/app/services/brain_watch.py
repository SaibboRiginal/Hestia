"""Brain watch — Oracle (the only brain) down for longer than ``argus.brain.grace``.

SPEC docs/work/2026-10-19-cervello-offline §1. Fed by the monitor cycle (no loop of its own):
- offline → presence signal ``brain.offline`` (Chronos overlay «Cervello offline», effect ``chat.reply=queued``;
  when it relaxes Chronos asks the chat clients to answer their queues) + one Hermes notice with fixed text
  (``replaces: system.brain``, one live notice);
- back → signal cleared + the notice closed with «di nuovo online».
While offline Argus never asks Oracle to narrate (fixed texts at once). A shorter outage (restart, deploy) says
nothing: chat clients queue their messages anyway.
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
SIGNAL = "brain.offline"
NOTICE_KEY = "system.brain"
_REFRESH_SECONDS = 600     # re-send the signal so its TTL never lapses while offline
_SIGNAL_TTL = 1800         # a dead Argus does not leave the overlay on forever

_lock = threading.Lock()
_state: dict = {"failing_since": None, "offline": False, "offline_since": None, "signal_at": 0.0, "reason": ""}

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


def observe(status: str | None, error: str | None = None, *, now: float | None = None) -> str | None:
    """One Oracle health observation (``None`` = not registered on Hub). Returns ``"offline"``/``"online"``
    on a transition, else ``None``."""
    now = time.time() if now is None else now
    healthy = status == "up"
    reason = "unregistered" if status is None else ("unreachable" if status == "down" else "unhealthy")
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
            if not _state["offline"] and now - failing_since >= cfg.get_int(cfg.BRAIN_GRACE, 0):
                _state.update(offline=True, offline_since=failing_since, signal_at=now)
                transition = "offline"
            elif _state["offline"] and now - _state["signal_at"] >= _REFRESH_SECONDS:
                _state["signal_at"] = now
                _signal(failing_since, reason)
    if transition == "offline":
        _go_offline(failing_since, reason, error)
    elif transition == "online":
        _go_online(now - (since or now))
    return transition


def _go_offline(since: float, reason: str, error: str | None) -> None:
    logger.warning("[🔄] event=brain_offline reason=%s error=%s", reason, str(error or "")[:200])
    _signal(since, reason)
    hermes_client.publish_event(
        domain="system", event_type="service.health", entity_id=NOTICE_KEY,
        payload={"_message": "🧠 <b>Cervello offline</b>: Oracle non risponde. Comandi, notifiche e agenda "
                             "funzionano; i messaggi in chat restano in coda e avranno risposta appena torna.",
                 "_title": "Cervello offline", "_level": "warning", "_source": "argus",
                 "replaces": NOTICE_KEY, "service": ORACLE, "status": "brain_offline", "reason": reason})


def _go_online(seconds_offline: float) -> None:
    logger.info("event=brain_online offline_for_s=%d", int(seconds_offline))
    if _presence is not None:
        _presence.clear(SIGNAL)
    hermes_client.publish_event(
        domain="system", event_type="service.health", entity_id=f"{NOTICE_KEY}.online",
        payload={"_message": f"🧠 <b>Di nuovo online</b> dopo {_minutes(seconds_offline)}: rispondo ai messaggi "
                             "rimasti in coda.",
                 "_title": "Cervello di nuovo online", "_level": "success", "_source": "argus",
                 "closes": NOTICE_KEY, "decision": "resolved", "outcome_text": "Di nuovo online",
                 "service": ORACLE, "status": "brain_online"})


def reset() -> None:
    """Tests only."""
    with _lock:
        _state.update(failing_since=None, offline=False, offline_since=None, signal_at=0.0, reason="")

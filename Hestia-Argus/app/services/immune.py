"""Immune system — a module that stays down is restarted, 1 to N times (docs/work/2026-10-19-oracle-offline v3 B).

Fed by the monitor cycle (no loop of its own). Argus decides, Hephaestus acts (``POST /api/hephaestus/restart``:
restart ``hestia_<svc>`` + health check, never itself, never during a Forge deploy of that service):
- down for ``argus.repair.restart_after`` seconds → restart 1; still down → restart again after twice the wait, up
  to ``argus.repair.max_restarts`` (Themis, 0 = never). Each try is an action of the incident (journal).
- every try failed → one Hermes notice with generic text (``replaces: system.repair.<svc>``), no more restarts;
- back up → the notice is closed («Back to normal»), counters reset.
Off with the existing «Automatic repair» (``argus.remediate.enabled``).
"""
from __future__ import annotations

import logging
import threading
import time

from core import argus_settings as cfg
from core import hermes_client, hub_client
from services import health_history
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger(f"hestia_argus.{__name__}")

NOTICE_EVENT = "service.action_required"   # always-on system subscription (like the «Unavailable» notice)
_NEVER = {"argus", "hephaestus", "hub"}     # who would restart them (Argus itself / Hephaestus / the only door)

_lock = threading.Lock()
_state: dict[str, dict] = {}   # service → {since, attempts, last_at, running, gave_up}


def notice_key(service: str) -> str:
    return f"system.repair.{service}"


def reset() -> None:
    """Tests only."""
    with _lock:
        _state.clear()


def snapshot() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _state.items()}


def observe(service: str, healthy: bool, *, now: float | None = None) -> str | None:
    """One health observation. Returns ``"restart"`` (a try started), ``"gave_up"``, ``"recovered"`` or None."""
    now = time.time() if now is None else now
    if healthy:
        with _lock:
            st = _state.pop(service, None)
        if st and st.get("attempts"):
            if st.get("gave_up"):
                _publish_back(service)
            logger.info("event=immune_recovered service=%s attempts=%s", service, st["attempts"])
            return "recovered"
        return None
    if service in _NEVER or not cfg.get_bool(cfg.REMEDIATE_ENABLED):
        return None
    limit = cfg.get_int(cfg.REPAIR_RESTARTS, 0)
    after = max(1, cfg.get_int(cfg.REPAIR_RESTART_AFTER, 1))
    with _lock:
        st = _state.setdefault(service, {"since": now, "attempts": 0, "last_at": None, "running": False,
                                         "gave_up": False})
        if st["running"] or st["gave_up"] or limit <= 0:
            return None
        due = st["since"] + after if not st["attempts"] else st["last_at"] + after * 2 ** st["attempts"]
        if now < due:
            return None
        if st["attempts"] >= limit:
            st["gave_up"] = True
            attempts = st["attempts"]
            action = "gave_up"
        else:
            st["attempts"] += 1
            st["running"], st["last_at"] = True, now
            attempts = st["attempts"]
            action = "restart"
    if action == "gave_up":
        _give_up(service, attempts)
    else:
        threading.Thread(target=_restart, args=(service, attempts, limit), daemon=True,
                         name=f"immune-{service}").start()
    return action


def _restart(service: str, attempt: int, limit: int) -> None:
    health_history.note_action(service, "restart", tr("Automatic restart {0}/{1}", attempt, limit))
    ok, res = hub_client.route("hephaestus", "api/hephaestus/restart", "POST",
                               {"service": service, "reason": "argus.immune", "attempt": attempt}, timeout=120)
    res = res if isinstance(res, dict) else {"detail": str(res)[:200]}
    healthy = bool(ok and res.get("healthy"))
    status = str(res.get("status") or ("error" if not ok else ""))
    text = {"ok": tr("Restarted and healthy again") if healthy else tr("Restarted, still not answering"),
            "skipped": tr("Restart left to the release in progress"), "refused": tr("Restart not allowed")}.get(
        status, tr("Restart failed"))
    health_history.note_action(service, "restart_result", text, ok=healthy)
    logger.info("[🔄] event=immune_restart_done service=%s attempt=%s status=%s healthy=%s",
                service, attempt, status, healthy)
    with _lock:
        st = _state.get(service)
        if st is not None:
            st["running"] = False
            if status in {"skipped", "refused"}:
                st["attempts"] -= 1 if status == "skipped" else 0   # a deploy window does not use up a try
                st["gave_up"] = st["gave_up"] or status == "refused"


def _give_up(service: str, attempts: int) -> None:
    logger.warning("[🔄] event=immune_gave_up service=%s attempts=%s", service, attempts)
    health_history.note_action(service, "gave_up", tr("I stop after {0} restarts: a hand is needed", attempts))
    hermes_client.publish_event(
        domain="system", event_type=NOTICE_EVENT, entity_id=notice_key(service),
        payload={"_message": tr("🩺 <b>A part of {assistant} does not restart by itself</b>: I tried {0} times. The rest works; the details are in the log of the Health page.", attempts),
                 "_title": tr("Does not restart by itself"), "_level": "warning", "_source": "argus",
                 "replaces": notice_key(service), "service": service, "status": "repair_gave_up"})


def _publish_back(service: str) -> None:
    hermes_client.publish_event(
        domain="system", event_type=NOTICE_EVENT, entity_id=f"{notice_key(service)}.back",
        payload={"_message": tr("✅ <b>Back in order</b>: the part that did not restart now works."),
                 "_title": tr("Back in order"), "_level": "success", "_source": "argus",
                 "closes": notice_key(service), "decision": "resolved", "outcome_text": tr("Back in order"),
                 "service": service, "status": "repair_back"})

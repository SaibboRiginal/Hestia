"""Alert worker — batched, deduplicated, Oracle-narrated notifications.

Flow
----
1. ``send_alert()`` is called by the monitor loop for every new log/health event.
2. The alert fingerprint is checked against the cooldown store — if already seen
   within ``argus.alerts.cooldown`` minutes (central setting, default 60) it is silently dropped.
3. New alerts are recorded immediately (before any I/O) so they can never be
   re-queued even if the flush fails.
4. Alerts are added to a pending queue and a flush timer is (re)started for
   ``argus.alerts.batch_window`` seconds (central setting, default 60).  Every new alert resets the
   timer, so a burst settles into a single dispatch.
5. When the timer fires, the whole batch is narrated by Oracle in one natural
   message in the owner's language and sent via Hermes as a single Telegram notification.
6. Recoveries bypass batching: they are sent immediately via Oracle.
7. While Oracle is offline (``oracle_watch``) Oracle is not asked: fixed text at once, no waits.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone

from core import argus_settings as cfg
from core import hermes_client, oracle_client
from schemas.reports import ServiceAlert
from services import oracle_watch
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger(f"hestia_argus.{__name__}")

# fingerprint → last dispatched time
_cooldown: dict[str, datetime] = {}
_cooldown_lock = threading.Lock()

# Pending batch
_pending: list[ServiceAlert] = []
_pending_lock = threading.Lock()

_flush_timer: threading.Timer | None = None
_flush_timer_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Fingerprinting & cooldown
# ---------------------------------------------------------------------------

def _health_fingerprint(service: str, status: str) -> str:
    return f"health:{service}:{status}"


def _log_fingerprint(service: str, level: str, message: str) -> str:
    # Suppress by service+level only so repeated errors from the same service
    # don't bypass cooldown due to slightly different message content.
    return f"log:{service}:{level}"


def _is_suppressed(fingerprint: str) -> bool:
    with _cooldown_lock:
        last = _cooldown.get(fingerprint)
    if last is None:
        return False
    return datetime.now(tz=timezone.utc) - last < timedelta(minutes=cfg.get_int(cfg.ALERT_COOLDOWN, 0))


def _record(fingerprint: str) -> None:
    with _cooldown_lock:
        _cooldown[fingerprint] = datetime.now(tz=timezone.utc)


def _clear(fingerprint: str) -> None:
    with _cooldown_lock:
        _cooldown.pop(fingerprint, None)


# ---------------------------------------------------------------------------
# Batching & flush
# ---------------------------------------------------------------------------

def _schedule_flush() -> None:
    """(Re)start the batch flush timer each time a new alert is enqueued."""
    global _flush_timer
    with _flush_timer_lock:
        if _flush_timer is not None:
            _flush_timer.cancel()
        _flush_timer = threading.Timer(float(cfg.get_int(cfg.ALERT_BATCH_WINDOW, 0)), _flush_batch)
        _flush_timer.daemon = True
        _flush_timer.start()


def _flush_batch() -> None:
    """Send all pending alerts as a single Oracle-narrated message."""
    with _pending_lock:
        batch = list(_pending)
        _pending.clear()

    if not batch:
        return

    logger.info("event=flushing_batch_alert Flushing batch of %d alert(s)", len(batch))
    text = _narrate_batch(batch)
    event_payload = {
        "_title": _title(batch),
        "_message": text,
        "_level": "warning",
        "_source": "argus",
        "alerts": [
            {"service": a.service, "kind": a.kind,
                "level": a.level, "message": a.message}
            for a in batch
        ],
    }
    ok = hermes_client.publish_event(
        domain="system",
        event_type="service.health",
        entity_id="argus-batch",
        payload=event_payload,
    )
    if ok:
        logger.info(
            "event=batch_alert_dispatched_subscriptions Batch of %d alert(s) dispatched via subscriptions", len(batch))
    else:
        logger.warning("event=batch_dispatch_failed_alert Batch dispatch failed (%d alert(s))", len(batch))


def _area(service: str) -> str:
    """People's name for the part of the assistant (never the module name)."""
    from hestia_common.areas import module_label
    return tr(module_label(service))


def _narrate_batch(alerts: list[ServiceAlert]) -> str:
    """Ask Oracle for a plain summary in the owner's language; fall back to one line per area (no module names,
    no raw log lines: the owner reads it)."""
    lines = []
    for a in alerts:
        area = _area(a.service)
        if a.kind == "health":
            lines.append(f"- area «{area}»: state {a.level.upper()} — {a.message[:200]}")
        elif a.kind == "performance":
            lines.append(f"- area «{area}» slow: {a.message[:200]}")
        else:
            lines.append(f"- area «{area}» [{a.level.upper()}]: {a.message[:300]}")
    raw = "\n".join(lines)

    prompt = (
        "You noticed these problems in your own system. Tell the owner, 3-4 short lines.\n"
        "- Which part is affected and what it means for him, plain words.\n"
        "- No module, service, file or code names, no raw errors, no ids.\n"
        "- Format: HTML <b> and <i> only. No Markdown, no JSON, no lists.\n\n"
        f"PROBLEMS:\n{raw}"
    )

    narrated = "" if oracle_watch.is_offline() else oracle_client.analyze(prompt, voice=True)
    if narrated and narrated.strip():
        return narrated.strip()

    # Fallback: one line per area (still a single message, not one per alert)
    by_area: dict[str, list[ServiceAlert]] = {}
    for a in alerts:
        by_area.setdefault(_area(a.service), []).append(a)
    out = []
    for area, items in by_area.items():
        down = any(a.kind == "health" for a in items)
        slow = all(a.kind == "performance" for a in items)
        what = (tr("«{0}» is not answering", area) if down else
                tr("«{0}» is slow", area) if slow else tr("«{0}» had errors", area))
        out.append(f"• {what}" + (f" · {tr('{0} times', len(items))}" if len(items) > 1 else ""))
    return "\n".join(out)


def _title(alerts: list[ServiceAlert]) -> str:
    return tr("Something is not working") if len(alerts) == 1 else tr("Some things are not working")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_alert(alert: ServiceAlert) -> None:
    """Enqueue an alert for batched Oracle-narrated dispatch."""
    if alert.kind == "health":
        fp = _health_fingerprint(alert.service, alert.level)
    elif alert.kind == "performance":
        fp = f"perf:{alert.service}:{alert.metric}"
    else:
        fp = _log_fingerprint(alert.service, alert.level, alert.message)

    if _is_suppressed(fp):
        logger.debug("event=alert_suppressed_cooldown_active Alert suppressed (cooldown active): %s", fp)
        return

    # Record immediately — prevents re-queuing even if the flush later fails
    _record(fp)

    with _pending_lock:
        _pending.append(alert)

    logger.debug("event=alert_enqueued_batch_window Alert enqueued for batch (window=%.0fs): %s",
                 float(cfg.get_int(cfg.ALERT_BATCH_WINDOW, 0)), fp)
    _schedule_flush()


def send_recovery(service: str) -> None:
    """Send a recovery notification immediately, bypassing the batch queue."""
    for status in ("down", "degraded"):
        _clear(_health_fingerprint(service, status))

    area = _area(service)
    prompt = (f"The part «{area}» of your own system works again. Tell the owner in one short line, plain words, "
              "no module or code names.")
    narrated = "" if oracle_watch.is_offline() else oracle_client.analyze(prompt, voice=True)
    text = narrated.strip() if narrated and narrated.strip() else tr("«{0}» works again.", area)

    hermes_client.publish_event(
        domain="system",
        event_type="service.health",
        entity_id=service,
        payload={"_title": tr("Working again"), "_message": text, "_level": "success", "_source": "argus",
                 "service": service, "status": "recovered"},
    )
    logger.info("event=recovery_notification_published Recovery notification published for: %s", service)

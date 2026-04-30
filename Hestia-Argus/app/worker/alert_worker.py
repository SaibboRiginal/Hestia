"""Alert worker — batched, deduplicated, Oracle-narrated notifications.

Flow
----
1. ``send_alert()`` is called by the monitor loop for every new log/health event.
2. The alert fingerprint is checked against the cooldown store — if already seen
   within ``ALERT_COOLDOWN_MINUTES`` (default 60) it is silently dropped.
3. New alerts are recorded immediately (before any I/O) so they can never be
   re-queued even if the flush fails.
4. Alerts are added to a pending queue and a flush timer is (re)started for
   ``ALERT_BATCH_WINDOW_SECONDS`` (default 20 s).  Every new alert resets the
   timer, so a burst settles into a single dispatch.
5. When the timer fires, the whole batch is narrated by Oracle in one natural
   Italian message and sent via Hermes as a single Telegram notification.
6. Recoveries bypass batching: they are sent immediately via Oracle.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from core import hermes_client, oracle_client
from schemas.reports import ServiceAlert

logger = logging.getLogger(f"hestia_argus.{__name__}")

COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "60"))
BATCH_WINDOW_SECONDS = float(os.getenv("ALERT_BATCH_WINDOW_SECONDS", "60"))

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
    return datetime.now(tz=timezone.utc) - last < timedelta(minutes=COOLDOWN_MINUTES)


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
        _flush_timer = threading.Timer(BATCH_WINDOW_SECONDS, _flush_batch)
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
        "_message": text,
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


def _narrate_batch(alerts: list[ServiceAlert]) -> str:
    """Ask Oracle for a natural Italian summary; fall back to compact plain text."""
    lines = []
    for a in alerts:
        if a.kind == "health":
            lines.append(
                f"- Servizio '{a.service}': stato {a.level.upper()} — {a.message}"
            )
        else:
            lines.append(
                f"- Servizio '{a.service}' [{a.level.upper()}]: {a.message[:300]}"
            )
    raw = "\n".join(lines)

    prompt = (
        f"Hestia ha rilevato i seguenti problemi nel sistema:\n\n"
        f"{raw}\n\n"
        f"Scrivi una breve notifica amichevole in italiano per l'utente (massimo 4-5 righe). "
        f"Menziona quali servizi sono coinvolti e cosa sembra succedere. "
        f"Puoi includere un breve estratto dell'errore grezzo se è utile. "
        f"Scrivi in modo naturale come se stessi informando qualcuno di un problema tecnico. "
        f"FORMATTAZIONE HTML TELEGRAM: usa <b>testo</b> per grassetto, <i>testo</i> per corsivo. "
        f"MAI usare sintassi Markdown (**testo**, _testo_, * item, - item). "
        f"Non usare JSON o elenchi puntati nel messaggio finale."
    )

    narrated = oracle_client.analyze(prompt)
    if narrated and narrated.strip():
        count = f" · {len(alerts)} eventi" if len(alerts) > 1 else ""
        return f"🔔 <b>Hestia Monitor{count}</b>\n\n{narrated.strip()}"

    # Fallback: compact grouped plain text (still a single message, not one per alert)
    by_service: dict[str, list[str]] = {}
    for a in alerts:
        by_service.setdefault(a.service, []).append(
            f"[{a.level}] {a.message[:200]}")

    fallback_lines = []
    for svc, msgs in by_service.items():
        fallback_lines.append(f"<b>{svc}</b>: {msgs[0]}")
        if len(msgs) > 1:
            fallback_lines.append(f"  <i>(+{len(msgs) - 1} altri)</i>")

    count = len(alerts)
    return (
        f"⚠️ <b>Hestia Monitor — {count} alert{'s' if count > 1 else ''}</b>\n\n"
        + "\n".join(fallback_lines)
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_alert(alert: ServiceAlert) -> None:
    """Enqueue an alert for batched Oracle-narrated dispatch."""
    if alert.kind == "health":
        fp = _health_fingerprint(alert.service, alert.level)
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
                 BATCH_WINDOW_SECONDS, fp)
    _schedule_flush()


def send_recovery(service: str) -> None:
    """Send a recovery notification immediately, bypassing the batch queue."""
    for status in ("down", "degraded"):
        _clear(_health_fingerprint(service, status))

    prompt = (
        f"Il servizio '{service}' di Hestia è tornato online correttamente. "
        f"Scrivi una breve notifica amichevole in italiano per informare l'utente della ripresa."
    )
    narrated = oracle_client.analyze(prompt)
    if narrated and narrated.strip():
        text = f"✅ <b>Hestia Monitor</b>\n\n{narrated.strip()}"
    else:
        text = f"✅ <b>Hestia Monitor</b>\n<code>{service}</code> è di nuovo online."

    hermes_client.publish_event(
        domain="system",
        event_type="service.health",
        entity_id=service,
        payload={"_message": text, "service": service, "status": "recovered"},
    )
    logger.info("event=recovery_notification_published Recovery notification published for: %s", service)

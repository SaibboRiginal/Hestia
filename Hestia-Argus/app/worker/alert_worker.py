"""Alert worker — deduplicated proactive notifications via Hermes → Telegram.

Alert path
----------
Argus sends alerts **directly through Hermes** (fast, no LLM round-trip) using
pre-formatted Telegram markdown.  Oracle is reserved for on-demand analysis.

Deduplication
-------------
Every alert is keyed by a *fingerprint*:
  - Health alerts:  ``health:{service}:{status}``
  - Log alerts:     ``log:{service}:{level}:{message_hash}`` (hash of first 120 chars)

A fingerprint is suppressed for ``ALERT_COOLDOWN_MINUTES`` (default 60) after
it fires.  When a service **recovers** (status → "up"), the health fingerprint
is cleared immediately and a recovery notification is sent.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from core import hermes_client
from schemas.reports import ServiceAlert

logger = logging.getLogger(__name__)

COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "60"))

# fingerprint → time it was last dispatched
_cooldown: dict[str, datetime] = {}
_cooldown_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def _health_fingerprint(service: str, status: str) -> str:
    return f"health:{service}:{status}"


def _log_fingerprint(service: str, level: str, message: str) -> str:
    msg_hash = hashlib.md5(message[:120].encode()).hexdigest()[:8]
    return f"log:{service}:{level}:{msg_hash}"


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
# Formatting
# ---------------------------------------------------------------------------

_LEVEL_EMOJI = {"WARNING": "⚠️", "ERROR": "🔴", "CRITICAL": "🚨", "DOWN": "💀"}
_STATUS_EMOJI = {"down": "💀", "degraded": "⚠️", "up": "✅"}


def _format_health_alert(alert: ServiceAlert) -> str:
    emoji = _STATUS_EMOJI.get(alert.level.lower(), "⚠️")
    return (
        f"{emoji} *Hestia Monitor — Service Alert*\n"
        f"Service: `{alert.service}`\n"
        f"Status: *{alert.level.upper()}*\n"
        f"Detail: {alert.message}"
    )


def _format_log_alert(alert: ServiceAlert) -> str:
    emoji = _LEVEL_EMOJI.get(alert.level.upper(), "⚠️")
    return (
        f"{emoji} *Hestia Monitor — Log Alert*\n"
        f"Service: `{alert.service}`\n"
        f"Level: *{alert.level.upper()}*\n"
        f"```\n{alert.message[:400]}\n```"
    )


def _format_recovery(service: str) -> str:
    return f"✅ *Hestia Monitor — Recovery*\nService `{service}` is back online."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_alert(alert: ServiceAlert) -> None:
    """Dispatch an alert via Hermes, respecting cooldown deduplication."""
    if alert.kind == "health":
        fp = _health_fingerprint(alert.service, alert.level)
        text = _format_health_alert(alert)
    else:
        fp = _log_fingerprint(alert.service, alert.level, alert.message)
        text = _format_log_alert(alert)

    if _is_suppressed(fp):
        logger.debug("Alert suppressed (cooldown active): %s", fp)
        return

    ok = hermes_client.send_message(text)
    if ok:
        _record(fp)
        logger.info("Alert dispatched via Hermes: %s", fp)
    else:
        logger.warning("Alert dispatch failed for: %s", fp)


def send_recovery(service: str) -> None:
    """Send a recovery notification and clear the service's health cooldown."""
    for status in ("down", "degraded"):
        _clear(_health_fingerprint(service, status))
    hermes_client.send_message(_format_recovery(service))
    logger.info("Recovery notification sent for: %s", service)

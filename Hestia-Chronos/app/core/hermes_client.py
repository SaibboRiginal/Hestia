"""Hermes client — send proactive notifications via Hermes dispatch."""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger("hestia_chronos.hermes_client")

_HERMES_URL = os.getenv("HERMES_URL", "http://hestia_hermes:19005")
_NOTIFY_TARGET = os.getenv("NOTIFY_TARGET", "")
_TIMEOUT = 8


def publish_event(domain: str, event_type: str, entity_id: str, payload: dict[str, Any]) -> bool:
    """Publish an event to Hermes for subscription-based delivery.

    Callers who have an active subscription for domain+event_type will receive
    the notification. The payload may include a ``_message`` key with a
    pre-formatted HTML string so Hermes skips Oracle narration.
    """
    body = {
        "domain": domain,
        "event_type": event_type,
        "entity_id": entity_id,
        "payload": payload,
    }
    try:
        resp = requests.post(
            f"{_HERMES_URL.rstrip('/')}/api/events/ingest",
            json=body,
            timeout=_TIMEOUT,
        )
        if resp.status_code < 300:
            result = (resp.json() if resp.content else {}).get("result", {})
            logger.info(
                "event=hermes_event_published_domain_event [HERMES] Event published domain=%s event=%s deliveries=%s",
                domain, event_type, result.get("deliveries", 0),
            )
            return True
        logger.warning("event=hermes_event_publish_status_body [HERMES] Event publish status=%s body=%s",
                       resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("event=hermes_publish_event_error [HERMES] publish_event error: %s", exc)
    return False


def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    """Legacy direct-send (bypasses subscriptions). Prefer publish_event."""
    target = chat_id or _NOTIFY_TARGET
    if not target:
        logger.warning(
            "event=hermes_notify_target_configured_skipping_notification [HERMES] No NOTIFY_TARGET configured — skipping notification")
        return False

    payload: dict[str, Any] = {
        "channel": "telegram",
        "target": target,
        "message": text,
        "metadata": {"source": "chronos", "type": "calendar_notification"},
    }
    try:
        resp = requests.post(
            f"{_HERMES_URL.rstrip('/')}/api/dispatch/send",
            json=payload,
            timeout=_TIMEOUT,
        )
        data = resp.json() if resp.content else {}
        if data.get("success", False) or resp.status_code < 300:
            return True
        logger.warning(
            "event=hermes_dispatch_returned_non_success [HERMES] Dispatch returned non-success status=%s body=%s",
            resp.status_code,
            resp.text[:200],
        )
    except Exception as exc:
        logger.warning("event=hermes_send_message_error [HERMES] send_message error: %s", exc)
    return False

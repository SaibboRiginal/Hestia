"""Hermes client — send pre-formatted alert messages to Telegram via Hermes.

Calls Hermes' ``POST /api/dispatch/send`` directly on the internal Docker
network.  Hermes handles the final delivery to Telegram, so Argus does not
need a bot token — it only needs the chat_id (``ARGUS_NOTIFY_TARGET``) and the
Hermes base URL.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(f"hestia_argus.{__name__}")

HERMES_URL = os.getenv(
    "HERMES_API_URL", "http://hestia_hermes:19005"
).rstrip("/")
NOTIFY_TARGET = os.getenv("ARGUS_NOTIFY_TARGET", "")


def publish_event(domain: str, event_type: str, entity_id: str, payload: dict[str, Any]) -> bool:
    """Publish an event to Hermes for subscription-based delivery.

    Include ``_message`` in *payload* with a pre-formatted HTML string so
    Hermes dispatches it as direct text without Oracle narration.
    """
    body = {
        "domain": domain,
        "event_type": event_type,
        "entity_id": entity_id,
        "payload": payload,
    }
    try:
        resp = requests.post(
            f"{HERMES_URL}/api/events/ingest", json=body, timeout=10)
        if resp.status_code < 300:
            result = (resp.json() if resp.content else {}).get("result", {})
            logger.info("event=hermes_event_published_domain_event [HERMES] Event published domain=%s event=%s deliveries=%s",
                        domain, event_type, result.get("deliveries", 0))
            return True
        logger.warning("event=hermes_publish_event_status_body [HERMES] publish_event status=%s body=%s",
                       resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.warning("event=hermes_publish_event_failed [HERMES] publish_event failed: %s", exc)
    return False


def send_message(text: str, chat_id: str | None = None) -> bool:
    """Legacy direct-send (bypasses subscriptions). Prefer publish_event."""
    target = chat_id or NOTIFY_TARGET
    if not target:
        logger.warning(
            "event=argus_notify_target_cannot_send_hermes_message No ARGUS_NOTIFY_TARGET configured; cannot send Hermes message."
        )
        return False

    payload = {
        "channel": "telegram",
        "target": str(target),
        "message": text,
        "metadata": {},
    }
    try:
        resp = requests.post(
            f"{HERMES_URL}/api/dispatch/send",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success", False):
            logger.warning("event=hermes_dispatch_returned_success_false Hermes dispatch returned success=false: %s", data)
            return False
        return True
    except Exception as exc:
        logger.warning("event=hermes_dispatch_failed Hermes dispatch failed: %s", exc)
        return False

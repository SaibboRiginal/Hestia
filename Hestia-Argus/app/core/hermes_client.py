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

HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api"
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
            f"{HUB_API_URL}/route/hermes/api/events/ingest",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": body,
                "timeout_seconds": 10,
            },
            timeout=11,
        )
        if resp.status_code != 200:
            logger.warning("event=hermes_publish_event_status_body [HERMES] publish_event status=%s body=%s",
                           resp.status_code, resp.text[:200])
            return False
        routed = resp.json() if resp.content else {}
        if int(routed.get("status_code", 500)) >= 400:
            logger.warning("event=hermes_publish_event_status_code [HERMES] publish_event status_code=%s",
                           routed.get("status_code"))
            return False
        result = (routed.get("payload") or {}).get("result", {}) if isinstance(routed.get("payload"), dict) else {}
        logger.info("event=hermes_event_published_domain_event [HERMES] Event published domain=%s event=%s deliveries=%s",
                    domain, event_type, result.get("deliveries", 0))
        return True
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

    dispatch_body = {
        "channel": "telegram",
        "target": str(target),
        "message": text,
        "metadata": {},
    }
    try:
        resp = requests.post(
            f"{HUB_API_URL}/route/hermes/api/dispatch/send",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": dispatch_body,
                "timeout_seconds": 10,
            },
            timeout=11,
        )
        if resp.status_code != 200:
            logger.warning("event=hermes_dispatch_status [HERMES] dispatch status=%s", resp.status_code)
            return False
        routed = resp.json() if resp.content else {}
        routed_payload = routed.get("payload") if isinstance(routed, dict) else {}
        if isinstance(routed_payload, dict) and routed_payload.get("success", False):
            return True
        logger.warning("event=hermes_dispatch_returned_success_false Hermes dispatch returned success=false: %s", routed_payload)
        return False
    except Exception as exc:
        logger.warning("event=hermes_dispatch_failed Hermes dispatch failed: %s", exc)
        return False

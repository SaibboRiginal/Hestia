"""Hermes client — send pre-formatted alert messages to Telegram via Hermes.

Calls Hermes' ``POST /api/dispatch/send`` directly on the internal Docker
network.  Hermes handles the final delivery to Telegram, so Argus does not
need a bot token — it only needs the chat_id (``ARGUS_NOTIFY_TARGET``) and the
Hermes base URL.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

HERMES_URL = os.getenv(
    "HERMES_API_URL", "http://hestia_hermes:19005"
).rstrip("/")
NOTIFY_TARGET = os.getenv("ARGUS_NOTIFY_TARGET", "")


def send_message(text: str, chat_id: str | None = None) -> bool:
    """Send a plain-text message to Telegram via Hermes dispatch.

    Uses ``chat_id`` if provided, otherwise falls back to ``ARGUS_NOTIFY_TARGET``.
    Returns ``True`` on success, ``False`` on any failure.
    """
    target = chat_id or NOTIFY_TARGET
    if not target:
        logger.warning(
            "No ARGUS_NOTIFY_TARGET configured; cannot send Hermes message."
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
            logger.warning("Hermes dispatch returned success=false: %s", data)
            return False
        return True
    except Exception as exc:
        logger.warning("Hermes dispatch failed: %s", exc)
        return False

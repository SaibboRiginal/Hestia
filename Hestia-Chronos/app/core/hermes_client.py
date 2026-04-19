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


def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    """Send a plain-text or HTML message to the user via Hermes.

    Uses NOTIFY_TARGET env as the default Telegram chat_id.
    Returns True when Hermes confirms delivery.
    """
    target = chat_id or _NOTIFY_TARGET
    if not target:
        logger.warning(
            "[HERMES] No NOTIFY_TARGET configured — skipping notification")
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
            "[HERMES] Dispatch returned non-success status=%s body=%s",
            resp.status_code,
            resp.text[:200],
        )
    except Exception as exc:
        logger.warning("[HERMES] send_message error: %s", exc)
    return False

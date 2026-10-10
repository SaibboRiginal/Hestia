"""Telegram → assistant presence: every message or button of the allowed user is an interaction
(SPEC docs/work/2026-10-10-assistant-presence). Debounced and in background: never slows a reply."""
from __future__ import annotations

import logging

from telegram_bot import core

logger = logging.getLogger("hestia_telegram.presence")

try:
    from hestia_common.presence_client import PresenceClient
    _presence = PresenceClient("telegram")
except Exception as exc:  # pragma: no cover - shared lib missing in odd local runs
    logger.warning("[🔄] event=presence_client_unavailable error=%s", exc)
    _presence = None


def touch(update, kind: str = "") -> None:
    """``update`` = a message or a callback query. ``kind``: chat | command (auto from the text)."""
    if _presence is None:
        return
    user = getattr(update, "from_user", None)
    if not core.is_allowed_user(getattr(user, "id", "")):
        return
    if not kind:
        text = str(getattr(update, "text", "") or "")
        kind = "command" if text.startswith("/") or hasattr(update, "data") else "chat"
    _presence.ping("telegram", kind)

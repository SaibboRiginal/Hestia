"""Taps → Metis usage log (docs/work/2026-10-24-tutto-brainstorm-cindy W6): each action started from a button or a
command is pushed in the background, so «Adesso» learns what is used when. Never blocks or fails the action."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from telegram_bot import catalog

logger = logging.getLogger("hestia_telegram.usage")


def tap(ref: str, kind: str = "tool", label: str = "") -> None:
    body = {"taps": [{"client": "telegram", "kind": kind, "ref": str(ref), "label": label,
                      "at": datetime.now(timezone.utc).isoformat()}]}

    def _send() -> None:
        ok, payload = catalog.route("metis", "api/metis/usage", "POST", body=body, timeout=6)
        if not ok:
            logger.info("[🔄] event=telegram_tap_not_sent ref=%s error=%s fallback=local_count_only", ref,
                        str(payload)[:120])
    threading.Thread(target=_send, daemon=True, name="telegram-tap").start()


def adesso(limit: int = 4) -> list[dict]:
    """«Adesso» items for the Oggi card ([] when Metis is away: the card keeps its fixed buttons)."""
    ok, payload = catalog.route("metis", "api/metis/adesso", query={"client": "telegram", "limit": limit}, timeout=6)
    items = payload.get("items") if ok and isinstance(payload, dict) else None
    return [i for i in items or [] if isinstance(i, dict) and i.get("tool")]

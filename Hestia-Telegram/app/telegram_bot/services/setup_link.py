"""Setup mode: link the owner with the one-time code of the guided setup (docs/work/2026-10-30-setup-un-click §4.2).

While no owner is configured (``ALLOWED_USER_ID`` empty) the bot is private to nobody and answers only to a
six-digit code: it hands the code and the sender's id to Hephaestus, which checks the code shown on the setup
screen (single use, 10 minutes, 5 tries), saves the id and restarts the bot. Nobody needs to know their numeric
Telegram id. With an owner configured this does nothing.
"""
from __future__ import annotations

import logging
import re

import requests

from .. import core

logger = logging.getLogger("hestia_telegram.setup_link")

_CODE = re.compile(r"^\s*(\d{6})\s*$")


def try_claim(message) -> bool:
    """True when the message was a setup code (answered here, whatever the outcome)."""
    if str(core.ALLOWED_USER_ID or "").strip():
        return False
    match = _CODE.match(str(getattr(message, "text", "") or ""))
    if not match:
        return False
    user_id = str(message.from_user.id)
    try:
        resp = requests.post(f"{core.HUB_API_URL}/route/hephaestus/api/setup/telegram/claim",
                             json={"method": "POST", "headers": {}, "query": {},
                                   "body": {"code": match.group(1), "user_id": user_id}, "timeout_seconds": 10},
                             timeout=15)
        payload = (resp.json() or {}).get("payload") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=setup_claim_unreachable error=%s", exc)
        core.bot.reply_to(message, "Non riesco a parlare con Hestia adesso. Riprova tra un minuto.")
        return True
    if payload.get("ok"):
        logger.info("event=setup_owner_claimed")
        core.bot.reply_to(message, "Fatto, ti riconosco! Tra pochi secondi riparto e sono tutta tua: scrivimi "
                                   "pure.")
    elif payload.get("reason") == "wrong_code":
        core.bot.reply_to(message, "Il codice non è giusto. Controlla quello sullo schermo del setup.")
    else:
        core.bot.reply_to(message, "Nessun codice attivo: apri il setup di Hestia e chiedine uno nuovo.")
    return True

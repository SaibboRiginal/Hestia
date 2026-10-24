"""WebUI pages inside Telegram (Mini App, docs/work/2026-10-23-telegram-da-zero §5.9 / T7).

A page that is a picture rather than an action (charts, the agenda week, photo galleries) opens the same WebUI page
inside Telegram. Telegram opens Mini Apps only on a public HTTPS address: with ``WEBUI_PUBLIC_URL`` (or the
Cloudflare tunnel host) set to ``https://…`` the button is a ``web_app`` button and the WebUI logs in with Telegram's
signed ``initData``; with a plain http address it is a normal link; with no public address no button is drawn and
every action still works with buttons.
"""
from __future__ import annotations

import logging
import os

from telegram_bot import core, ui

logger = logging.getLogger("hestia_telegram.webapp")


def public_url() -> str:
    url = os.getenv("WEBUI_PUBLIC_URL", "").strip().rstrip("/")
    if not url and os.getenv("CLOUDFLARE_TUNNEL_HOSTNAME", "").strip():
        url = "https://" + os.getenv("CLOUDFLARE_TUNNEL_HOSTNAME", "").strip().strip("/")
    return url


def page_url(path: str = "/") -> str:
    base = public_url()
    if not base:
        return ""
    return base + "/" + str(path or "").lstrip("/")


def open_button(label: str, path: str = "/"):
    """«Apri …» for a WebUI page: Mini App on https, link on http, nothing without a public address."""
    url = page_url(path)
    if not url:
        return None
    if url.startswith("https://"):
        sep = "&" if "?" in url else "?"
        return ui.button(label, web_app=f"{url}{sep}tg=1")
    return ui.button(label, url=url)


def set_menu_button() -> None:
    """The chat's menu button «Apri Hestia» (only with a public https address)."""
    url = page_url("/")
    if not url.startswith("https://"):
        return
    try:
        from telebot.types import MenuButtonWebApp, WebAppInfo
        core.bot.set_chat_menu_button(menu_button=MenuButtonWebApp("web_app", "Apri Hestia",
                                                                    WebAppInfo(f"{url}?tg=1")))
        logger.info("event=telegram_menu_button_set")
    except Exception as exc:  # noqa: BLE001
        logger.info("event=telegram_menu_button_failed error=%s", exc)


MAX_AGE_SECONDS = 24 * 3600     # an older initData (a reopened, cached page) asks to reopen from Telegram


def verify_init_data(init_data: str, now: float | None = None) -> dict:
    """Check Telegram's signed Mini App launch data (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).

    The WebUI asks this through the Hub (the bot token stays in this module): ``{ok, user_id}`` only for a fresh
    signature of this bot and a user in ALLOWED_USER_ID; ``{ok: False, reason}`` otherwise (no detail of why the
    hash differs)."""
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import parse_qsl

    pairs = dict(parse_qsl(str(init_data or ""), keep_blank_values=True))
    given = pairs.pop("hash", "")
    if not given or not core.TELEGRAM_TOKEN:
        return {"ok": False, "reason": "missing"}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", core.TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, given):
        logger.warning("event=webapp_login_refused reason=signature")
        return {"ok": False, "reason": "signature"}
    try:
        age = (now or time.time()) - int(pairs.get("auth_date") or 0)
    except ValueError:
        age = MAX_AGE_SECONDS + 1
    if age > MAX_AGE_SECONDS:
        logger.info("event=webapp_login_refused reason=expired")
        return {"ok": False, "reason": "expired"}
    try:
        user_id = str((json.loads(pairs.get("user") or "{}") or {}).get("id") or "")
    except ValueError:
        user_id = ""
    if not user_id or not core.is_allowed_user(user_id):
        logger.warning("event=webapp_login_refused reason=user")
        return {"ok": False, "reason": "user"}
    logger.info("event=webapp_login_ok")
    return {"ok": True, "user_id": user_id}

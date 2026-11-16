"""Deterministic handling of pasted OAuth redirect URLs.

Google's loopback flow ends on ``http://localhost:.../api/gateway/auth/callback/<provider>?code=...``.
On a phone that page cannot load, so the user pastes the URL in chat.  Sending it
through the LLM is fragile (small local models may not call the right tool), so
Telegram recognises the pattern and forwards it straight to Hecate via Hub.
"""
from __future__ import annotations

import html
import logging
import re
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

_CALLBACK_RE = re.compile(
    r"(https?://\S*/api/gateway/auth/callback/(?P<provider>[a-z]+)\?\S*(?:code|error)=\S+)",
    re.IGNORECASE,
)


def match_oauth_callback(text: str) -> tuple[str, str] | None:
    """Return ``(provider, url)`` when *text* contains an OAuth callback URL."""
    found = _CALLBACK_RE.search(str(text or ""))
    if not found:
        return None
    return found.group("provider").lower(), found.group(1)


def complete_oauth_from_paste(provider: str, url: str) -> str:
    """Forward the pasted URL to Hecate and return an HTML reply."""
    from telegram_bot import catalog
    ok, payload = catalog.route("hecate", f"api/gateway/auth/complete/{provider}", "POST", body={"code": url})
    name = html.escape(provider.capitalize())
    if ok and isinstance(payload, dict) and payload.get("status") == "authorized":
        return tr("🟢 <b>{0} linked</b>\nThe calendar is active.", name)
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        msg = str(detail.get("error") or detail)
        hint = str(detail.get("hint") or "")
    else:
        msg, hint = str(detail or tr("unknown error")), ""
    logging.getLogger("hestia_telegram.oauth").warning("event=oauth_paste_failed provider=%s detail=%s", provider,
                                                         msg[:300])
    reply = tr("🔴 <b>Linking {0} failed</b>", name)
    reply += f"\n{html.escape(hint[:300])}" if hint else tr("\nStart again from the beginning: the link lasts a few minutes.")
    return reply

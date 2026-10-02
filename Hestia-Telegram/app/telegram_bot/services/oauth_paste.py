"""Deterministic handling of pasted OAuth redirect URLs.

Google's loopback flow ends on ``http://localhost:.../api/gateway/auth/callback/<provider>?code=...``.
On a phone that page cannot load, so the user pastes the URL in chat.  Sending it
through the LLM is fragile (small local models may not call the right tool), so
Telegram recognises the pattern and forwards it straight to Hecate via Hub.
"""
from __future__ import annotations

import html
import re

from telegram_bot.services.router import route_service_command

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
    ok, payload = route_service_command(
        service="hecate",
        path=f"/api/gateway/auth/complete/{provider}",
        method="POST",
        query={},
        body={"code": url},
    )
    name = html.escape(provider.capitalize())
    if ok and isinstance(payload, dict) and payload.get("status") == "authorized":
        return f"✅ <b>{name} collegato.</b> Calendario attivo."
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    if isinstance(detail, dict):
        msg = str(detail.get("error") or detail)
        hint = str(detail.get("hint") or "")
    else:
        msg, hint = str(detail or "errore sconosciuto"), ""
    reply = f"⚠️ Collegamento {name} non riuscito: {html.escape(msg[:300])}"
    if hint:
        reply += f"\n<i>{html.escape(hint[:300])}</i>"
    return reply

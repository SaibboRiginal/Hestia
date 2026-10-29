"""Bank / payment app notifications from the phone (Cindy 32, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4).

Hecate pushes ``phone.notification`` items ``{app, title, text, at}`` (feed ``hestia_common.feeds``); a notification
that clearly says money moved («Pagamento di 12,50 € presso ESSELUNGA», «Hai ricevuto 20 €») becomes a transaction
to review, like a PayPal mail. Anything else is ignored. Deterministic: no model call.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .catalog import find_currency, parse_amount

_MONEY = re.compile(r"(?:€|EUR|USD|\$|£)\s?(-?\d[\d.,]*)|(-?\d[\d.,]*)\s?(?:€|EUR|euro|USD|\$|£)", re.I)
_IN = re.compile(r"accredit|ricevut|in entrata|rimbors|hai ricevuto|received|refund|stipendio", re.I)
_OUT = re.compile(r"pagament|pagato|addebit|spes[oa]|acquist|prelievo|paid|payment|purchase|transazione|"
                  r"autorizzat|hai inviato|sent", re.I)
_MERCHANT = re.compile(r"\b(?:presso|da|a|at|to|from|su|verso)\s+([A-Za-z0-9][\w&'.*\- ]{1,40}?)"
                       r"(?=\s+(?:il|con|di|in|on|alle|per)\b|[.,;:!]|$)")


def parse(app: str, title: str, text: str) -> dict[str, Any] | None:
    """``{kind: expense|income, amount (positive), currency, merchant}`` or None."""
    full = f"{title or ''}\n{text or ''}"
    m = _MONEY.search(full)
    if not m:
        return None
    amount = parse_amount(m.group(1) or m.group(2))
    if amount is None or amount == 0:
        return None
    if _IN.search(full):
        kind = "income"
    elif _OUT.search(full) or amount < 0:
        kind = "expense"
    else:
        return None
    who = _MERCHANT.search(text or "") or _MERCHANT.search(title or "")
    merchant = who.group(1).strip(" .-*") if who else ""
    return {"kind": kind, "amount": abs(amount), "currency": find_currency(m.group(0), find_currency(full)),
            "merchant": merchant[:80] or str(app or "")[:80]}


def ref(item: dict) -> str:
    raw = "|".join(str(item.get(k) or "") for k in ("app", "title", "text")) + "|" + str(item.get("at") or "")[:16]
    return "phone:" + hashlib.sha1(raw.encode()).hexdigest()[:16]

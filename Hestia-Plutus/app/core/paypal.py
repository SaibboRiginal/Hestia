"""PayPal receipt mails → transactions (deterministic first; Oracle only when a money mail is not understood).

PayPal sends one mail per payment, refund or money received, in the owner's language. The parser reads the subject
and body text (HTML already flattened by Hecate) and returns what it is sure about. No real receipts in the repo:
tests use synthetic ones shaped like the public templates.
"""
from __future__ import annotations

import re
from typing import Any

from hestia_common.i18n import word_regex, words

from .catalog import find_currency, parse_amount

# kind, subject/body patterns (lowercase, words of every language). The first match wins.
_KINDS = [("refund", word_regex("{0}", "plutus.paypal.refund")),
          ("received", word_regex("{0}", "plutus.paypal.received")),
          ("payment", word_regex("{0}", "plutus.paypal.payment"))]

_MONEY_HINT = word_regex("{0}", "plutus.money_hint")

_MERCHANT_RES = [re.compile(p, re.I) for p in words("plutus.paypal.merchant")]
_AMOUNT_RES = [
    word_regex(r"(?:{0})[^\d€$£\n-]{{0,30}}(-?\s*[€$£]?\s*\d[\d.,']*\s*(?:€|EUR|USD|GBP|\$|£)?)",
               "plutus.paypal.amount_label"),
    re.compile(r"([€$£]\s*\d[\d.,']*\s*(?:EUR|USD|GBP)?|\d[\d.,']*\s*(?:€|EUR|USD|GBP))", re.I),
]
_TXN_RE = word_regex(r"(?:{0})\s*[:\n#]?\s*([A-Z0-9]{{10,20}})", "plutus.paypal.transaction_id")


def looks_like_money(subject: str, body: str = "") -> bool:
    return bool(_MONEY_HINT.search(subject or "") or _MONEY_HINT.search((body or "")[:400]))


def _clean_merchant(m: str) -> str:
    m = re.sub(r"\s+", " ", m or "").strip(" :.,\"'")
    m = re.sub(r"\s+(?:di|for|per|of)\s+[-€$£]?\s*\d.*$", "", m, flags=re.I)
    return m[:80]


def parse(subject: str, body: str) -> dict[str, Any] | None:
    """``{kind, amount (signed), currency, merchant, txn_id}`` or None when the mail is not a money mail we
    understand. Payment → negative, refund/received → positive."""
    subject, body = subject or "", body or ""
    text = f"{subject}\n{body}"
    low = text.lower()
    kind = next((k for k, pattern in _KINDS if re.search(pattern, low)), None)
    if not kind:
        return None
    amount = None
    for rx in _AMOUNT_RES:
        for m in rx.finditer(text):
            value = parse_amount(m.group(1))
            if value is not None and abs(value) > 0:
                amount = abs(value)
                currency = find_currency(m.group(1), find_currency(text))
                break
        if amount is not None:
            break
    if amount is None:
        return None
    merchant = ""
    for rx in _MERCHANT_RES:
        m = rx.search(subject) or rx.search(body)
        if m and _clean_merchant(m.group(1)):
            merchant = _clean_merchant(m.group(1))
            break
    txn = _TXN_RE.search(text)
    return {"kind": kind, "amount": -amount if kind == "payment" else amount, "currency": currency,
            "merchant": merchant or "PayPal", "txn_id": txn.group(1).upper() if txn else ""}

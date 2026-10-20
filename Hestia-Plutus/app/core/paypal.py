"""PayPal receipt mails → transactions (deterministic first; Oracle only when a money mail is not understood).

PayPal sends one mail per payment, refund or money received, in Italian or English. The parser reads the subject
and body text (HTML already flattened by Hecate) and returns what it is sure about. No real receipts in the repo:
tests use synthetic ones shaped like the public templates.
"""
from __future__ import annotations

import re
from typing import Any

from .catalog import find_currency, parse_amount

# kind, subject/body patterns (lowercase). The first match wins.
_KINDS = [
    ("refund", r"rimborso|refund|ti (?:è|e) stato rimborsato|you(?:'ve| have) (?:got|received) a refund"),
    ("received", r"hai ricevuto (?:denaro|un pagamento|\d)|you(?:'ve| have)? received (?:money|a payment|\d)|"
                 r"ti ha inviato|sent you"),
    ("payment", r"ricevuta|hai inviato un pagamento|hai pagato|hai autorizzato un pagamento|pagamento a|"
                r"receipt for your payment|you sent a payment|you(?:'ve| have)? paid|you authorized a payment|"
                r"payment to|il tuo pagamento|your payment|abbonamento|subscription|ordine|order"),
]

_MONEY_HINT = re.compile(r"pagament|ricevut|rimbors|denaro|addebit|payment|receipt|refund|money|order|ordine|"
                         r"abbonament|subscription", re.I)

_MERCHANT_RES = [
    re.compile(r"(?:pagamento|payment)\s+(?:a|to)\s+(.+?)(?:\s+(?:di|for|per|of)\s+[-€$£\d]|[.\n|]|$)", re.I),
    re.compile(r"(?:hai inviato|you sent)\s+(?:un pagamento|a payment)?\s*(?:di|of)?\s*[^\n]*?\s+(?:a|to)\s+(.+?)(?:[.\n|]|$)",
               re.I),
    re.compile(r"(?:rimborso|refund)\s+(?:da|from)\s+(.+?)(?:[.\n|]|$)", re.I),
    re.compile(r"(.+?)\s+(?:ti ha inviato|ti ha rimborsato|sent you|has sent you|refunded)", re.I),
    re.compile(r"(?:esercente|venditore|merchant|seller)\s*[:\n]\s*(.+?)(?:\n|$)", re.I),
]
_AMOUNT_RES = [
    re.compile(r"(?:importo|totale|total|amount|pagamento di|payment of|hai inviato|you sent|hai ricevuto|you received|"
               r"rimborso di|refund of|hai pagato|you paid)[^\d€$£\n-]{0,30}(-?\s*[€$£]?\s*\d[\d.,']*\s*(?:€|EUR|USD|GBP|\$|£)?)",
               re.I),
    re.compile(r"([€$£]\s*\d[\d.,']*\s*(?:EUR|USD|GBP)?|\d[\d.,']*\s*(?:€|EUR|USD|GBP))", re.I),
]
_TXN_RE = re.compile(r"(?:id (?:della )?transazione|transaction id|codice transazione|id transazione)\s*[:\n#]?\s*"
                     r"([A-Z0-9]{10,20})", re.I)


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

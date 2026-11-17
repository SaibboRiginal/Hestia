"""Plutus seed data and text helpers: default categories (editable data, not code rules), default merchant rules,
money parsing that understands both decimal formats (1.234,56 and 1,234.56)."""
from __future__ import annotations

import re
import unicodedata

from hestia_common.i18n import word_regex, words

# id, label, icon, color, kind (expense | income | transfer)
CATEGORIES = [
    ("groceries", "Groceries", "cart", "green", "expense"),
    ("home", "Home and bills", "home", "blue", "expense"),
    ("transport", "pl::Transport", "car", "teal", "expense"),
    ("restaurants", "Restaurants and bars", "coffee", "orange", "expense"),
    ("subscriptions", "Subscriptions", "repeat", "purple", "expense"),
    ("health", "Health", "heart", "red", "expense"),
    ("care", "Personal care", "sparkle", "pink", "expense"),
    ("leisure", "Leisure", "music", "amber", "expense"),
    ("shopping", "Shopping", "bag", "indigo", "expense"),
    ("travel", "pl::Travel", "plane", "cyan", "expense"),
    ("gifts", "Gifts", "gift", "rose", "expense"),
    ("work", "Work and study", "briefcase", "slate", "expense"),
    ("other", "Other", "dots", "gray", "expense"),
    ("income", "f.pl::Income", "arrow-down", "green", "income"),
    ("transfers", "Transfers", "swap", "gray", "transfer"),
]

RULE_CATEGORIES = ("groceries", "home", "transport", "restaurants", "subscriptions", "health", "care", "leisure",
                   "shopping", "travel")


def default_rules() -> dict[str, list[str]]:
    """Pattern (lowercase substring of merchant/description) → category, from the words of every language
    (``plutus.rule.<category>`` in ``locales/<lang>/words.json``). Seeded once, editable by the user."""
    return {cid: list(words(f"plutus.rule.{cid}")) for cid in RULE_CATEGORIES}


def slug(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def norm_merchant(text: str | None) -> str:
    """Comparable merchant name: lowercase, no accents, no PayPal/card prefixes or trailing codes."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^(paypal\s*\*|pp\*|sumup\s*\*|sq\s*\*|zettle_\*)", "", t.strip())
    t = word_regex(r"^(?:{0})", "plutus.merchant_prefix").sub("", t)
    t = re.sub(r"\b(srl|s\.r\.l\.|spa|s\.p\.a\.|ltd|inc|gmbh|sa)\b\.?", "", t)
    t = re.sub(r"[#*]\s*\w*\d\w*", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip(" .-,")


_AMOUNT_RE = re.compile(r"[-+−]?\s*\d{1,3}(?:[.,\s'’]\d{3})*(?:[.,]\d{1,2})?(?!\d)|[-+−]?\s*\d+(?:[.,]\d{1,2})?")


def parse_amount(text: str | float | int | None) -> float | None:
    """'1.234,56' · '1,234.56' · '12,99' · '-5' · '€ 12.99' → float (sign kept). None when there is no number."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return round(float(text), 2)
    s = str(text).replace("−", "-").replace(" ", " ")
    m = _AMOUNT_RE.search(s)
    if not m:
        return None
    raw = re.sub(r"[\s'’]", "", m.group(0))
    neg = raw.startswith("-")
    raw = raw.lstrip("+-")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".") if raw.rfind(",") > raw.rfind(".") else raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        raw = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else raw.replace(",", "")
    elif raw.count(".") == 1 and len(raw.rpartition(".")[2]) == 3:
        raw = raw.replace(".", "")            # 1.234 = thousands
    try:
        value = round(float(raw), 2)
    except ValueError:
        return None
    return -value if neg else value


CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "CHF": "CHF", "EUR": "EUR", "USD": "USD", "GBP": "GBP"}


def find_currency(text: str, default: str = "EUR") -> str:
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in (text or ""):
            return code
    return default

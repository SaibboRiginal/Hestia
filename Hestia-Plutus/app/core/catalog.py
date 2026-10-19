"""Plutus seed data and text helpers: default categories (editable data, not code rules), default merchant rules,
money parsing that understands Italian and English formats."""
from __future__ import annotations

import re
import unicodedata

# id, label, icon, color, kind (expense | income | transfer)
CATEGORIES = [
    ("spesa", "Spesa", "cart", "green", "expense"),
    ("casa", "Casa e bollette", "home", "blue", "expense"),
    ("trasporti", "Trasporti", "car", "teal", "expense"),
    ("ristoranti", "Ristoranti e bar", "coffee", "orange", "expense"),
    ("abbonamenti", "Abbonamenti", "repeat", "purple", "expense"),
    ("salute", "Salute", "heart", "red", "expense"),
    ("cura", "Cura personale", "sparkle", "pink", "expense"),
    ("svago", "Svago", "music", "amber", "expense"),
    ("shopping", "Shopping", "bag", "indigo", "expense"),
    ("viaggi", "Viaggi", "plane", "cyan", "expense"),
    ("regali", "Regali", "gift", "rose", "expense"),
    ("lavoro", "Lavoro e studio", "briefcase", "slate", "expense"),
    ("altro", "Altro", "dots", "gray", "expense"),
    ("entrate", "Entrate", "arrow-down", "green", "income"),
    ("trasferimenti", "Trasferimenti", "swap", "gray", "transfer"),
]

# pattern (lowercase substring of merchant/description) → category. Seeded once, editable by the user.
DEFAULT_RULES = {
    "spesa": ["esselunga", "coop", "conad", "lidl", "carrefour", "eurospin", "pam ", "despar", "aldi", "penny market",
              "iper", "naturasi", "tigros", "bennet", "famila"],
    "casa": ["enel", "a2a", "iren", "hera", "edison", "tim ", "vodafone", "iliad", "fastweb", "windtre", "wind tre",
             "ikea", "leroy merlin", "affitto", "condominio"],
    "trasporti": ["trenitalia", "italo", "atm ", "uber", "freenow", "telepass", "autostrade", "eni ", "q8", "tamoil",
                  "esso", "ip ", "benzina", "parcheggio", "bike", "lime", "bird"],
    "ristoranti": ["ristorante", "pizzeria", "trattoria", "osteria", "bar ", "caffe", "mcdonald", "burger king",
                   "deliveroo", "glovo", "just eat", "starbucks", "sushi"],
    "abbonamenti": ["netflix", "spotify", "disney", "prime video", "amazon prime", "youtube premium", "dazn", "now tv",
                    "icloud", "google one", "apple.com/bill", "chatgpt", "openai", "anthropic", "claude.ai", "github"],
    "salute": ["farmacia", "parafarmacia", "medico", "dentista", "ospedale", "analisi", "ottica"],
    "cura": ["sephora", "douglas", "kiko", "parrucchiere", "barbiere", "estetista", "lookfantastic", "notino"],
    "svago": ["cinema", "teatro", "concerto", "ticketone", "steam", "playstation", "nintendo", "xbox", "libreria",
              "feltrinelli", "mondadori"],
    "shopping": ["amazon", "zalando", "zara", "h&m", "decathlon", "mediaworld", "unieuro", "ebay", "aliexpress",
                 "vinted", "shein", "uniqlo"],
    "viaggi": ["booking.com", "airbnb", "ryanair", "easyjet", "ita airways", "expedia", "hotel", "flixbus"],
}


def slug(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def norm_merchant(text: str | None) -> str:
    """Comparable merchant name: lowercase, no accents, no PayPal/card prefixes or trailing codes."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"^(paypal\s*\*|pp\*|sumup\s*\*|sq\s*\*|zettle_\*|pagamento\s+(pos|carta)\s+)", "", t.strip())
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

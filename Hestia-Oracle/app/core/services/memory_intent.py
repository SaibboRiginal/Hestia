"""Memory intent detection — pure functions, no I/O, no side effects.

Each function returns a boolean indicating whether the user message
contains an explicit intent of the corresponding type.
"""
from __future__ import annotations

import re

_NOTIFICATION_KEYWORDS = frozenset({
    "avvisami", "notifica", "notifiche", "alert", "fammi sapere",
    "voglio essere avvisato", "voglio essere avvisata", "mandami", "inviami",
    "attiva notifica", "attiva notifiche", "seguimi", "monitor", "monitorare",
})

_PREFERENCE_KEYWORDS = frozenset({
    "preferisco", "mi piace", "non mi piace", "vorrei", "voglio", "cerco",
    "evita", "evitare", "odio", "amo", "interessa", "budget", "zona",
    "stanze", "metri", "prefer", "i like", "i don't like", "i want",
    "looking for", "avoid",
})

_SYNTHETIC_FRAGMENTS = frozenset(
    {"hermes", "oracle", "assistant", "hestia", "telegram"})

_DEPRECATE_KEYWORDS = frozenset({
    "cancella", "rimuovi", "elimina", "dimentica", "reset",
    "togli", "delete", "remove", "forget", "clear",
})


def has_notification_intent(user_message: str) -> bool:
    """Return True when *user_message* contains an explicit notification request."""
    message = str(user_message or "").strip().lower()
    return bool(message) and any(kw in message for kw in _NOTIFICATION_KEYWORDS)


def has_preference_intent(user_message: str) -> bool:
    """Return True when *user_message* contains an explicit preference statement."""
    message = str(user_message or "").strip().lower()
    return bool(message) and any(kw in message for kw in _PREFERENCE_KEYWORDS)


def has_deprecate_intent(user_message: str) -> bool:
    """Return True when *user_message* explicitly requests removal of stored data."""
    message = str(user_message or "").strip().lower()
    return bool(message) and any(kw in message for kw in _DEPRECATE_KEYWORDS)


def is_fact_grounded_in_message(fact: str, user_message: str) -> bool:
    """Return True when *fact* has meaningful token overlap with *user_message*.

    Rejects facts that reference synthetic system names absent from the user's text.
    """
    fact_text = str(fact or "").strip().lower().replace("_", " ")
    user_text = str(user_message or "").strip().lower()
    if not fact_text or not user_text:
        return False

    for fragment in _SYNTHETIC_FRAGMENTS:
        if fragment in fact_text and fragment not in user_text:
            return False

    fact_tokens = {t for t in re.findall(
        r"[a-zA-Z0-9à-öø-ÿ]+", fact_text) if len(t) >= 4}
    user_tokens = {t for t in re.findall(
        r"[a-zA-Z0-9à-öø-ÿ]+", user_text) if len(t) >= 4}
    if not fact_tokens or not user_tokens:
        return False
    return bool(fact_tokens & user_tokens)


# ── Selective memory gate (Claude-like: remember what matters, not every message) ──
_NOISE = re.compile(
    r"^(ciao|hey|ehi|ehy|hola|ok|okay|grazie|thanks|test|testing|prova|provo|si|sì|no|va bene|perfetto|"
    r"buongiorno|buonasera|buonanotte|bene|ottimo|top|capito|chiaro|daje|lol|ahah|ah ok|ok grazie)[\s!.?…]*$",
    re.IGNORECASE)
_REMEMBER = ("ricorda", "ricordati", "tieni a mente", "segnati", "memorizza", "non dimenticare",
             "da ora in poi", "d'ora in poi", "sempre ", "mai più", "remember", "from now on")
_SELF = re.compile(
    r"\b(io|mi chiamo|mio|mia|miei|mie|sono (?:un|una|nato|nata|di|allergic\w*|vegan\w*|vegetarian\w*)|"
    r"ho (?:un|una|due|tre|quattro|\d+)|abito|vivo a|lavoro (?:come|a|in|da|per)|studio|preferisco|odio|amo|"
    r"mia moglie|mio marito|mio figlio|mia figlia|la mia|il mio|i am|i'm|my|i have|i live|i work)\b",
    re.IGNORECASE)


def is_memory_worthy(user_message: str) -> bool:
    """Cheap gate before the LLM memory extractor.

    True only for messages that can carry a durable fact about the user: explicit
    "ricorda/d'ora in poi", removal or notification requests, first-person facts and
    preferences. Greetings, tests, acknowledgements and plain questions → False.
    """
    text = str(user_message or "").strip()
    if len(text) < 12 or _NOISE.match(text):
        return False
    low = text.lower()
    if any(k in low for k in _REMEMBER) or has_deprecate_intent(low) or has_notification_intent(low):
        return True
    if text.endswith("?"):
        return False   # questions ask, they don't state facts
    return bool(_SELF.search(low)) or has_preference_intent(low)


_WRITE_INTENT = re.compile(
    r"\b(salva|ricorda|memorizza|cancella|elimina|rimuovi|dimentica|aggiungi|crea|imposta|modifica|cambia|"
    r"sposta|annulla|attiva|disattiva|avvisami|notificami|prenota|programma|pianifica|invia|manda|segna)\w*",
    re.IGNORECASE)


def has_write_intent(user_message: str) -> bool:
    """True when the user asks to change something (save, create, delete, schedule, send…)."""
    return bool(_WRITE_INTENT.search(str(user_message or "")))


# ── Same fact, other words (bench with a real model, 2026-10-30: one «lavoro come sviluppatore…» → 3 rows) ──
_FACT_STOP = frozenset({
    "utente", "l'utente", "the", "user", "che", "con", "per", "una", "uno", "del", "della", "dello", "dei", "delle",
    "alla", "alle", "allo", "dalla", "dalle", "dal", "nel", "nella", "sul", "sulla", "come", "suo", "sua", "suoi",
    "sue", "mio", "mia", "miei", "mie", "sono", "essere", "di", "solito", "anche", "molto",
})


def _fact_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for tok in re.findall(r"[a-zà-öø-ÿ0-9]+", str(text or "").lower()):
        if tok.isdigit():
            out.add(tok.lstrip("0") or "0")
        elif len(tok) >= 3 and tok not in _FACT_STOP:
            out.add(tok[:5])   # crude stem: lavoro/lavora, allergico/allergica
    return out


def same_fact(new_fact: str, old_fact: str, threshold: float = 0.8) -> bool:
    """True when *new_fact* adds (almost) nothing to *old_fact*: ≥ threshold of its words are already there."""
    new, old = _fact_tokens(new_fact), _fact_tokens(old_fact)
    return bool(new) and len(new & old) / len(new) >= threshold


def asks_to_remember(user_message: str) -> bool:
    """«ricorda / tieni a mente / d'ora in poi…»: the user wants it kept as a memory, whatever else the turn did."""
    low = str(user_message or "").lower()
    return any(k in low for k in _REMEMBER) and not low.lstrip().startswith("ricordami")

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

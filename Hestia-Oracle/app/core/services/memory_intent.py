"""Memory intent detection — pure functions, no I/O, no side effects.

Each function returns a boolean indicating whether the user message
contains an explicit intent of the corresponding type.
"""
from __future__ import annotations

import re

from hestia_common.i18n import word_regex, word_set, words

# What the owner writes, in every language with a words file (hestia_common.i18n.words, docs/LANGUAGES.md).
def _has(key: str, message: str) -> bool:
    return any(kw in message for kw in words(key))


_SYNTHETIC_FRAGMENTS = frozenset(
    {"hermes", "oracle", "assistant", "hestia", "telegram"})



def has_notification_intent(user_message: str) -> bool:
    """Return True when *user_message* contains an explicit notification request."""
    message = str(user_message or "").strip().lower()
    return bool(message) and _has("memory.notify", message)


def has_preference_intent(user_message: str) -> bool:
    """Return True when *user_message* contains an explicit preference statement."""
    message = str(user_message or "").strip().lower()
    return bool(message) and _has("memory.preference", message)


def has_deprecate_intent(user_message: str) -> bool:
    """Return True when *user_message* explicitly requests removal of stored data."""
    message = str(user_message or "").strip().lower()
    return bool(message) and _has("memory.forget", message)


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
_NOISE = word_regex(r"^(?:{0})[\s!.?…]*$", "memory.noise")
_SELF = word_regex(r"\b(?:{0})\b", "memory.self")


def is_memory_worthy(user_message: str) -> bool:
    """Cheap gate before the LLM memory extractor.

    True only for messages that can carry a durable fact about the user: explicit
    "remember / from now on", removal or notification requests, first-person facts and
    preferences. Greetings, tests, acknowledgements and plain questions → False.
    """
    text = str(user_message or "").strip()
    if len(text) < 12 or _NOISE.match(text):
        return False
    low = text.lower()
    if _has("memory.remember", low) or has_deprecate_intent(low) or has_notification_intent(low):
        return True
    if text.endswith("?"):
        return False   # questions ask, they don't state facts
    return bool(_SELF.search(low)) or has_preference_intent(low)


_WRITE_INTENT = word_regex(r"\b(?:{0})\w*", "memory.write")


def has_write_intent(user_message: str) -> bool:
    """True when the user asks to change something (save, create, delete, schedule, send…)."""
    return bool(_WRITE_INTENT.search(str(user_message or "")))


# ── Same fact, other words (bench with a real model, 2026-10-30: one «I work as a developer…» → 3 rows) ──


def _fact_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for tok in re.findall(r"[a-zà-öø-ÿ0-9]+", str(text or "").lower()):
        if tok.isdigit():
            out.add(tok.lstrip("0") or "0")
        elif len(tok) >= 3 and tok not in word_set("memory.fact_stop"):
            out.add(tok[:5])   # crude stem: work/works, allergic/allergy
    return out


def same_fact(new_fact: str, old_fact: str, threshold: float = 0.8) -> bool:
    """True when *new_fact* adds (almost) nothing to *old_fact*: ≥ threshold of its words are already there."""
    new, old = _fact_tokens(new_fact), _fact_tokens(old_fact)
    return bool(new) and len(new & old) / len(new) >= threshold


def asks_to_remember(user_message: str) -> bool:
    """«remember / keep in mind / from now on…» (any language): the user wants it kept as a memory, whatever else the turn did."""
    low = str(user_message or "").lower()
    return _has("memory.remember", low) and not any(low.lstrip().startswith(w) for w in words("memory.remind_me"))

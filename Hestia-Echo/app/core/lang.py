"""The language of the conversation (Marko 2026-11-07: «the voice must speak the language I speak, whatever it is»).

``detect(text)`` reads the language of a text to speak, so every voice speaks it with a voice of that language
instead of an Italian voice reading English (or the other way round). Short or unclear texts keep the fallback.
"""
from __future__ import annotations

import logging
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("echo.lang")

NAMES = {"it": "lang::Italian", "en": "lang::English", "es": "lang::Spanish", "fr": "lang::French", "de": "lang::German", "pt": "lang::Portuguese",
         "ja": "lang::Japanese", "zh": "lang::Chinese", "hi": "lang::Hindi", "nl": "lang::Dutch", "pl": "lang::Polish", "ru": "lang::Russian"}
# What the setup's «Listen» says, in the language of the voice tried: ``locales/<code>/voice.json`` (``sample``, and
# ``default_name`` for scripts that do not use Latin letters). ``{assistant}`` is the name the owner gave her
# (docs/work/2026-11-16-nome-ovunque). Each sentence is in its own language on purpose (the voice of that language reads it).


def sample(code: str, ident: dict[str, str] | None = None) -> str:
    """The «Listen» sentence in ``code`` (the owner's language when unknown) with the assistant's name and gender."""
    from hestia_common import identity
    from hestia_common.i18n import catalog, current
    ident = dict(ident or identity.default())
    voice = catalog("voice", code) or catalog("voice", current()) or catalog("voice", "en")
    native = voice.get("default_name")
    if native and (ident.get("assistant") or identity.DEFAULT_NAME) == identity.DEFAULT_NAME:
        ident["assistant"] = native
    return identity.named(str(voice.get("sample") or ""), ident)


MIN_CHARS = 12
MIN_PROB = 0.80


def detect(text: str, fallback: str) -> str:
    """Two-letter language of ``text``; ``fallback`` when it is too short or the guess is unsure."""
    t = (text or "").strip()
    if len(t) < MIN_CHARS:
        return fallback
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0                      # same text → same answer
        best = detect_langs(t)[0]
    except Exception as exc:  # noqa: BLE001 — no detector or no letters: keep the conversation's language
        logger.debug("event=voice_lang_detect_skipped error=%s", exc)
        return fallback
    if best.prob < MIN_PROB:
        return fallback
    return best.lang.split("-")[0]


def name(code: str) -> str:
    return tr(NAMES[(code or "")[:2]]) if (code or "")[:2] in NAMES else (code or "")

"""The language of the conversation (Marko 2026-11-07: «la voce deve parlare la lingua con cui parlo io, qualsiasi»).

``detect(text)`` reads the language of a text to speak, so every voice speaks it with a voice of that language
instead of an Italian voice reading English (or the other way round). Short or unclear texts keep the fallback.
"""
from __future__ import annotations

import logging
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("echo.lang")

NAMES = {"it": "lang::Italian", "en": "lang::English", "es": "lang::Spanish", "fr": "lang::French", "de": "lang::German", "pt": "lang::Portuguese",
         "ja": "lang::Japanese", "zh": "lang::Chinese", "hi": "lang::Hindi", "nl": "lang::Dutch", "pl": "lang::Polish", "ru": "lang::Russian"}
# What the setup's «Ascolta» says, in the language of the voice tried. ``{assistant}`` is the name the owner gave her
# (docs/work/2026-11-16-name-everywhere); scripts that do not use Latin letters keep their own spelling only for the
# default name. Each sentence is in its own language on purpose (the voice of that language reads it).
SAMPLE = {"it": "Ciao, sono {assistant}. Questa è la mia voce.", "en": "Hi, I'm {assistant}. This is my voice.",
          "es": "Hola, soy {assistant}. Esta es mi voz.", "fr": "Bonjour, je suis {assistant}. Voici ma voix.",
          "de": "Hallo, ich bin {assistant}. Das ist meine Stimme.",
          "pt": "Olá, eu sou {g:a|o} {assistant}. Esta é a minha voz.",
          "ja": "こんにちは、{assistant}です。これが私の声です。", "zh": "你好，我是{assistant}。这是我的声音。",
          "hi": "नमस्ते, मैं {assistant} हूँ। यह मेरी आवाज़ है।"}
_NATIVE_DEFAULT = {"ja": "ヘスティア", "zh": "赫斯提亚", "hi": "हेस्टिया"}


def sample(code: str, ident: dict[str, str] | None = None) -> str:
    """The «Ascolta» sentence in ``code`` (Italian when unknown) with the assistant's name and gender."""
    from hestia_common import identity
    ident = dict(ident or identity.default())
    code = code if code in SAMPLE else "it"
    if code in _NATIVE_DEFAULT and (ident.get("assistant") or identity.DEFAULT_NAME) == identity.DEFAULT_NAME:
        ident["assistant"] = _NATIVE_DEFAULT[code]
    return identity.named(SAMPLE[code], ident)


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

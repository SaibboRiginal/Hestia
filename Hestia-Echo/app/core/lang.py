"""The language of the conversation (Marko 2026-11-07: «la voce deve parlare la lingua con cui parlo io, qualsiasi»).

``detect(text)`` reads the language of a text to speak, so every voice speaks it with a voice of that language
instead of an Italian voice reading English (or the other way round). Short or unclear texts keep the fallback.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("echo.lang")

NAMES = {"it": "italiano", "en": "inglese", "es": "spagnolo", "fr": "francese", "de": "tedesco", "pt": "portoghese",
         "ja": "giapponese", "zh": "cinese", "hi": "hindi", "nl": "olandese", "pl": "polacco", "ru": "russo"}
# What the setup's «Ascolta» says, in the language of the voice tried.
SAMPLE = {"it": "Ciao, sono Hestia. Questa è la mia voce.", "en": "Hi, I'm Hestia. This is my voice.",
          "es": "Hola, soy Hestia. Esta es mi voz.", "fr": "Bonjour, je suis Hestia. Voici ma voix.",
          "de": "Hallo, ich bin Hestia. Das ist meine Stimme.", "pt": "Olá, eu sou a Hestia. Esta é a minha voz.",
          "ja": "こんにちは、ヘスティアです。これが私の声です。", "zh": "你好，我是赫斯提亚。这是我的声音。",
          "hi": "नमस्ते, मैं हेस्टिया हूँ। यह मेरी आवाज़ है।"}
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
    return NAMES.get((code or "")[:2], code or "")

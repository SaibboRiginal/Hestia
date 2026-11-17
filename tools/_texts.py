"""Texts of the host tools (tools/*.py) in the owner's language, from the same catalogs as the modules.

The host has no Themis: the language is ``HESTIA_LANGUAGE`` when set, else the system locale (``LANG``…), else
English. ``tr("{0} written", path)`` = English source → ``Hestia-Shared/hestia_common/locales/<lang>/messages.json``.
Words people type (a yes) come from ``words.json`` of every language, as in the modules (docs/LANGUAGES.md).
"""
from __future__ import annotations

import json
import locale
import os
from functools import lru_cache
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "Hestia-Shared" / "hestia_common" / "locales"


def language() -> str:
    for raw in (os.getenv("HESTIA_LANGUAGE"), os.getenv("LC_ALL"), os.getenv("LC_MESSAGES"), os.getenv("LANG"),
                (locale.getlocale()[0] or "")):
        code = str(raw or "").strip().lower()[:2]
        if code.isalpha() and len(code) == 2 and code not in ("c", "po"):
            return code
    return "en"


@lru_cache(maxsize=None)
def _catalog(name: str, lang: str) -> dict:
    try:
        return json.loads((LOCALES / lang / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tr(text: str, *args: object) -> str:
    out = _catalog("messages", language()).get(text) or text.split("::", 1)[-1]
    return out.format(*args) if args else out


def is_yes(answer: str) -> bool:
    a = str(answer or "").strip().lower()
    words = {"y", "yes"}
    for d in LOCALES.iterdir() if LOCALES.is_dir() else []:
        words |= {w.lower() for w in _catalog("words", d.name).get("common.yes_word", [])}
    return a in words

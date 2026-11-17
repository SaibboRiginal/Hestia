"""Labels of the listing pages (Italian sites write Italian labels): ``scout.label.<key>`` in
``locales/<lang>/words.json``, every language read, so a site in another language is one more list entry."""
from __future__ import annotations

from hestia_common.i18n import word_regex, word_set, words


def has(key: str, text: str) -> bool:
    """``text`` contains one of the label words of ``key``."""
    return any(w in text for w in words(f"scout.label.{key}"))


def label_is(key: str, text: str) -> bool:
    """``text`` is exactly one of the label words of ``key``."""
    return text in word_set(f"scout.label.{key}")


def none_value(value: str) -> bool:
    """«no», «assente», «nessuno»… in any language."""
    v = value.strip().lower()
    return v == "no" or v in word_set("scout.value.none")


def yes_value(value: str) -> bool:
    """«Sì», «Sì, 2», «Yes»… in any language."""
    return value.strip().lower().split(",")[0].strip() in word_set("common.yes_word")


__all__ = ["has", "label_is", "none_value", "yes_value", "word_regex"]

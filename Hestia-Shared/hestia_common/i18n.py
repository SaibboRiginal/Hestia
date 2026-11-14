"""Texts people read, in their language (dossier docs/work/2026-11-14-backend-inglese).

Everything the model reads is English and lives in the code (tool descriptions, prompts). Everything a person
reads comes from ``hestia_common/locales/<lang>/<catalog>.json``; a missing language or key falls back to
Italian, then to what the caller passes. The language is the personal setting ``themis.personal.language``
(``identity.LANGUAGE``): a module reads it with its own ``SettingsClient`` after ``follow_personal()``.

Catalog ``tools``: ``{tool_name: {"summary": "...", "params": {param: "help"}}}``.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

LOCALES = Path(__file__).parent / "locales"
FALLBACK = "it"


@lru_cache(maxsize=32)
def catalog(name: str, lang: str = FALLBACK) -> dict:
    """One catalog of one language (``{}`` when missing)."""
    path = LOCALES / str(lang or FALLBACK)[:2] / f"{name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def language(get: Callable[[str], Any] | None = None) -> str:
    """The owner's language code from a ``settings.get``-like reader (missing → Italian)."""
    from hestia_common import identity
    if get is None:
        return FALLBACK
    try:
        return identity.language_code(get(identity.LANGUAGE))
    except Exception:  # noqa: BLE001 - a text is never lost because settings are unreachable
        return FALLBACK


def tool_text(tool: str, lang: str = FALLBACK) -> dict:
    """The people texts of a tool: ``{"summary"?, "params"?}`` in ``lang``, else Italian, else ``{}``."""
    for code in dict.fromkeys((str(lang or FALLBACK)[:2], FALLBACK)):
        entry = catalog("tools", code).get(str(tool or ""))
        if isinstance(entry, dict):
            return entry
    return {}


def tool_summary(tool: str, lang: str = FALLBACK) -> str:
    return str(tool_text(tool, lang).get("summary") or "")


def param_help(tool: str, param: str, lang: str = FALLBACK) -> str:
    params = tool_text(tool, lang).get("params")
    return str(params.get(param) or "") if isinstance(params, dict) else ""


# ── fixed texts (catalog ``messages``: ``{italian source text: translation}``) ─────────────────────────────────
# The Italian text in the code is the key: a language without a translation shows English when there is one,
# else the Italian source. The language reader is registered once per process by
# ``SettingsClient.follow_personal()``; a caller may pass ``lang`` explicitly.
_reader: Callable[[str], Any] | None = None
_CHAIN_TAIL = ("en",)


def use(get: Callable[[str], Any] | None) -> None:
    """Register the ``settings.get`` that answers ``themis.personal.language`` for this process."""
    global _reader
    _reader = get


def current() -> str:
    """The owner's language for this process (Italian when no reader is registered)."""
    return language(_reader)


def t(text: Any, *args: Any, lang: str | None = None, **kwargs: Any) -> str:
    """``text`` (Italian source) in the owner's language; with arguments it is then ``str.format``-ed.

    ``t("Ciao {name}", name=n)`` · ``t("{0} file", count)``. Never raises: a broken translation falls back to the
    source text."""
    source = "" if text is None else str(text)
    code = str(lang or current())[:2]
    out = source
    if code != FALLBACK and source:
        for c in dict.fromkeys((code, *_CHAIN_TAIL)):
            hit = catalog("messages", c).get(source)
            if isinstance(hit, str) and hit:
                out = hit
                break
    if not (args or kwargs):
        return out
    try:
        return out.format(*args, **kwargs)
    except (IndexError, KeyError, ValueError):
        try:
            return source.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return source

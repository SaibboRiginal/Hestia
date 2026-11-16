"""Texts people read, in their language (dossier docs/work/2026-11-14-backend-inglese).

The code is English, always (standard: ``docs/LANGUAGES.md``). Everything the model reads lives in the code as
English; every fixed text a person reads is written in English in the code and translated through
``hestia_common/locales/<lang>/<catalog>.json`` (today: ``it``). A missing key shows the English source. The
language is the personal setting ``themis.personal.language`` (``identity.LANGUAGE``): a module reads it with its own
``SettingsClient`` after ``follow_personal()``.

A source text may carry a context tag, ``"f::Active"``, when one English text needs two translations (gender,
number, two meanings): the tag picks the catalog entry and is never shown.

Catalog ``tools``: ``{tool_name: {"summary": "...", "params": {param: "help"}}}``.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

LOCALES = Path(__file__).parent / "locales"
FALLBACK = "it"   # the owner's language when the setting is unknown
SOURCE = "en"     # the language of every text in the code
_CTX = re.compile(r"^[a-z][a-z0-9.]*::")


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
    """The people texts of a tool: ``{"summary"?, "params"?}`` in ``lang``, else English, else ``{}``."""
    code = str(lang or FALLBACK)[:2]
    for code in dict.fromkeys((code, SOURCE, "it")):
        entry = catalog("tools", code).get(str(tool or ""))
        if isinstance(entry, dict):
            return entry
    return {}


def tool_summary(tool: str, lang: str = FALLBACK) -> str:
    return str(tool_text(tool, lang).get("summary") or "")


def param_help(tool: str, param: str, lang: str = FALLBACK) -> str:
    params = tool_text(tool, lang).get("params")
    return str(params.get(param) or "") if isinstance(params, dict) else ""


# ── fixed texts (catalog ``messages``: ``{english source text: translation}``) ─────────────────────────────────
# The English text in the code is the key; a language without the entry shows the English source. The language
# reader is registered once per process by ``SettingsClient.follow_personal()``; a caller may pass ``lang``.
_reader: Callable[[str], Any] | None = None


def use(get: Callable[[str], Any] | None) -> None:
    """Register the ``settings.get`` that answers ``themis.personal.language`` for this process."""
    global _reader
    _reader = get


def current() -> str:
    """The owner's language for this process (Italian when no reader is registered)."""
    return language(_reader)


def bare(text: str) -> str:
    """The source text without its context tag (``"f::Active"`` → ``"Active"``)."""
    return _CTX.sub("", text, count=1)


def t(text: Any, *args: Any, lang: str | None = None, **kwargs: Any) -> str:
    """``text`` (English source) in the owner's language; with arguments it is then ``str.format``-ed.

    ``t("Hello {name}", name=n)`` · ``t("{0} files", count)``. Never raises: a broken translation falls back to the
    source text."""
    source = "" if text is None else str(text)
    code = str(lang or current())[:2]
    plain = bare(source)
    out = plain
    if code != SOURCE and source:
        hit = catalog("messages", code).get(source)
        if isinstance(hit, str) and hit:
            out = hit
    if not (args or kwargs):
        return out
    try:
        return out.format(*args, **kwargs)
    except (IndexError, KeyError, ValueError):
        try:
            return plain.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return plain


# Keys whose string value a person reads: a client localizes them when a payload crosses to the owner.
LABEL_KEYS = frozenset({"title", "label", "subtitle", "summary", "description", "help", "group", "hint",
                        "placeholder", "unit", "section", "caption", "empty", "tooltip", "action_label",
                        "button", "heading", "badge", "note"})


def localize(payload: Any, lang: str | None = None) -> Any:
    """A copy of a JSON payload whose people texts (values of ``LABEL_KEYS`` that are catalog keys) are in the
    owner's language. Ids, statuses and user data stay as they are; English needs no work."""
    code = str(lang or current())[:2]
    if code == SOURCE:
        return payload
    table = catalog("messages", code)
    if not table:
        return payload

    def walk(node: Any, key: str = "") -> Any:
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str) and key in LABEL_KEYS:
            hit = table.get(node)
            return hit if isinstance(hit, str) and hit else node
        return node
    return walk(payload)

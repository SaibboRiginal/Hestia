"""Texts people read, in their language (dossier docs/work/2026-11-14-english-backend).

The code is English, always (standard: ``docs/LANGUAGES.md``). Everything the model reads lives in the code as
English; every fixed text a person reads is written in English in the code and translated through
``hestia_common/locales/<lang>/<catalog>.json`` (today: ``it``). A missing key shows the English source. The
language is the personal setting ``themis.personal.language`` (``identity.LANGUAGE``): a module reads it with its own
``SettingsClient`` after ``follow_personal()``.

A source text may carry a context tag, ``"f::Active"``, when one English text needs two translations (gender,
number, two meanings): the tag picks the catalog entry and is never shown.

Catalog ``tools``: ``{tool_name: {"summary": "...", "params": {param: "help"}}}``.

Catalog ``words``: the words a parser looks for in what the owner writes (``{name: [word, ...]}``), one file per
language (``locales/<lang>/words.json``). ``words(name)`` joins every language, so the owner may write in any of them
and a new language is only a new file: the code never holds those words.
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


def languages() -> tuple[str, ...]:
    """Every language with a folder under ``locales`` (English first: the source)."""
    try:
        found = sorted(p.name for p in LOCALES.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))
    except OSError:
        found = []
    return tuple(dict.fromkeys([SOURCE, *found]))


@lru_cache(maxsize=256)
def words(name: str, lang: str | None = None) -> tuple[str, ...]:
    """The words of list *name* (``locales/<lang>/words.json``): of one language, or of all of them (no *lang*)."""
    out: list[str] = []
    for code in ((str(lang)[:2],) if lang else languages()):
        value = catalog("words", code).get(str(name or ""))
        if isinstance(value, str):
            value = [value]
        out.extend(str(w) for w in (value or []) if str(w))
    return tuple(dict.fromkeys(out))


def words_pattern(name: str, lang: str | None = None, *, whole: bool = True) -> str:
    """A regex alternation of the words of *name* (longest first, escaped; each word may itself be a regex when the
    list name ends in ``_re``)."""
    items = sorted(words(name, lang), key=len, reverse=True)
    parts = items if name.endswith("_re") else [re.escape(w) for w in items]
    body = "|".join(parts) or r"(?!x)x"
    return rf"\b(?:{body})\b" if whole else f"(?:{body})"


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


def identity_now() -> dict:
    """Who the assistant is for this process (its name and she/he), from the same reader; defaults without one."""
    from hestia_common import identity
    if _reader is None:
        return identity.default()
    try:
        return identity.read(_reader)
    except Exception:  # noqa: BLE001 - a text is never lost because settings are unreachable
        return identity.default()


def _named(*texts: str) -> tuple[str, ...]:
    """``{assistant}`` and ``{g:lei|lui}`` filled with the assistant's chosen name and gender (``identity.named``)."""
    if not any("{assistant}" in x or "{g:" in x for x in texts):
        return texts
    from hestia_common import identity
    ident = identity_now()
    return tuple(identity.named(x, ident) for x in texts)


def bare(text: str) -> str:
    """The source text without its context tag (``"f::Active"`` → ``"Active"``)."""
    return _CTX.sub("", text, count=1)


def t(text: Any, *args: Any, lang: str | None = None, **kwargs: Any) -> str:
    """``text`` (English source) in the owner's language; with arguments it is then ``str.format``-ed.

    ``t("Hello {name}", name=n)`` · ``t("{0} files", count)``. ``{assistant}`` and ``{g:lei|lui}`` take the
    assistant's chosen name and gender (``identity.named``) before formatting. Never raises: a broken translation
    falls back to the source text."""
    source = "" if text is None else str(text)
    code = str(lang or current())[:2]
    plain = bare(source)
    out = plain
    if code != SOURCE and source:
        hit = catalog("messages", code).get(source)
        if isinstance(hit, str) and hit:
            out = hit
    out, plain = _named(out, plain)
    if not (args or kwargs):
        return out
    try:
        return out.format(*args, **kwargs)
    except (IndexError, KeyError, ValueError):
        try:
            return plain.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return plain


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def month_name(month: int, lang: str | None = None) -> str:
    """Name of ``month`` (1-12) in the owner's language («gennaio» in Italian)."""
    return t(MONTHS[(int(month) - 1) % 12], lang=lang)


def weekday_name(weekday: int, lang: str | None = None) -> str:
    """Name of ``weekday`` (0 = Monday, as ``date.weekday()``) in the owner's language, lower case."""
    return t(WEEKDAYS[int(weekday) % 7], lang=lang)


# Keys whose string value is never a people text (ids, codes, states): ``localize`` leaves them alone.
KEEP_KEYS = frozenset({"id", "key", "value", "status", "state", "type", "kind", "slug", "path", "url", "href",
                       "code", "icon", "color", "tone", "module", "service", "method", "tool", "command",
                       "domain", "source", "role", "lang", "language", "page", "link", "view", "tab", "event",
                       "event_type", "use_case", "provider", "model", "format", "mime", "unit_code", "action",
                       "name_id", "entity_id", "dedupe_key", "replaces", "query", "q", "args", "params"})
# Kept keys whose value is the owner's data even as a list or object (a setting value, tool arguments): never walked.
# Under the other kept keys a list or object (a plugin's ``page`` list, an ``action`` button) holds people texts.
DATA_KEYS = frozenset({"id", "key", "value", "query", "q", "args", "params", "replaces"})


def localize(payload: Any, lang: str | None = None) -> Any:
    """A copy of a JSON payload whose people texts are in the owner's language: every string value that is a
    catalog key (an English source text) is translated, except under ``KEEP_KEYS``. Module-level labels (manifests,
    pages, widgets, cards, choices) are written in English and translated here, at the edge to the owner."""
    code = str(lang or current())[:2]
    table = catalog("messages", code) if code != SOURCE else {}

    def text(node: str) -> str:
        hit = table.get(node)
        out = hit if isinstance(hit, str) and hit else (bare(node) if _CTX.match(node) else node)
        return _named(out)[0]

    def walk(node: Any, key: str = "") -> Any:
        if isinstance(node, dict):
            # KEEP_KEYS protect string values (ids, keys, states); a list or object under such a key (a plugin's
            # ``page`` list, an ``action`` button) still holds people texts and is walked.
            return {k: (v if k in KEEP_KEYS and (isinstance(v, str) or k in DATA_KEYS) else walk(v, k))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str):
            return text(node)
        return node
    return walk(payload)

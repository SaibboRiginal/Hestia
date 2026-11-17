"""Texts people read, in their language (dossier docs/work/2026-11-14-english-backend).

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
    """``{assistant}`` and ``{g:her-form|his-form}`` filled with the assistant's chosen name and gender (``identity.named``)."""
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

    ``t("Hello {name}", name=n)`` · ``t("{0} files", count)``. ``{assistant}`` and ``{g:her-form|his-form}`` take the
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
    """Name of ``month`` (1-12) in the owner's language («January» in English)."""
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
            return {k: (v if k in KEEP_KEYS else walk(v, k)) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str):
            return text(node)
        return node
    return walk(payload)


# ── words people write (catalog ``words``: ``{list key: [regex fragments]}``, one file per language) ───────────
# Parsers of what the owner writes (yes/no, «delete», dates, moods, bank mails…) never hold a language in the code:
# they name a list (``"oracle.delete_ask"``) and read it from every ``locales/<lang>/words.json``, so the owner is
# understood in any language that has a file, whatever «Language» says. Entries are regex fragments (``"delet"``,
# ``"alread[y]"``); a new language is one new file.
@lru_cache(maxsize=1)
def _languages() -> tuple[str, ...]:
    return tuple(sorted(p.name for p in LOCALES.iterdir() if (p / "words.json").is_file()))


def languages() -> tuple[str, ...]:
    """Every language Hestia knows (one folder in ``locales/``), English first."""
    return tuple(sorted(_languages(), key=lambda c: c != SOURCE))


@lru_cache(maxsize=512)
def words(key: str) -> tuple[str, ...]:
    """Every entry of the list ``key`` in every language with a ``words.json`` (English first, no duplicates)."""
    out: list[str] = []
    for code in sorted(_languages(), key=lambda c: c != SOURCE):
        for w in catalog("words", code).get(key) or []:
            if isinstance(w, str) and w and w not in out:
                out.append(w)
    return tuple(out)


def alt(key: str) -> str:
    """The entries of ``key`` as one regex alternation (``a|b|c``), longest first; ``(?!)`` when empty."""
    items = sorted(words(key), key=len, reverse=True)
    return "|".join(items) if items else "(?!)"


@lru_cache(maxsize=512)
def word_regex(template: str, *keys: str, flags: int = re.IGNORECASE) -> "re.Pattern[str]":
    """A compiled regex where ``{0}``, ``{1}``… in ``template`` are the alternations of ``keys``:
    ``word_regex(r"\\b(?:{0})\\w*", "oracle.delete_ask")``."""
    return re.compile(template.format(*(alt(k) for k in keys)), flags)


def word_set(key: str) -> frozenset[str]:
    """The entries of ``key`` as plain lower-case words (lists of whole words, not fragments)."""
    return frozenset(w.lower() for w in words(key))


def is_yes(value: Any) -> bool:
    """True for a boolean typed as text: ``1``, ``true`` or a yes word of any language (``common.yes_word``)."""
    return value if isinstance(value, bool) else str(value).strip().lower() in {"1", "true"} | word_set("common.yes_word")


def weekday_of(name: str) -> int:
    """Monday = 0 … Sunday = 6 for a weekday name or its first three letters in any language (``date.weekday.<n>``);
    ``ValueError`` when it is not one."""
    low = str(name or "").strip().lower()
    for n in range(7):
        if any(low in (w, w[:3]) for w in word_set(f"date.weekday.{n}")):
            return n
    raise ValueError(name)

"""Who the assistant is and whose it is (docs/work/2026-11-12-identity-and-proactivity).

Five personal settings owned by Themis (``settings_client.PERSONAL``): the owner's name, how to call him, the
assistant's name (default «Hestia»), whether it is a she or a he, and the language of what she writes on her own. Every prompt that speaks to the owner is
written once with tokens and rendered with :func:`render`:

- ``{assistant}``         → the assistant's name
- ``{owner}``             → how to call the owner (``the person writing to you`` while unknown)
- ``{owner_rule}``        → one sentence: his name, or «ask him» while unknown
- ``{g:her-form|his-form}`` → the first form for a she, the second for a he
- ``{owner_language}``    → the owner's language in English («Italian», «English»…): notifications, recaps and
  every text she writes on her own use it. In chat she answers in the language the owner just wrote in.

A module reads the values with its own ``SettingsClient`` after ``follow_personal()``::

    ident = identity.read(settings.get)
    text = identity.render(TEMPLATE, ident)

The repository, the modules and the releases keep the name Hestia; the voice and the clients take the chosen name.

Texts people read (buttons, notices, help) use the same two tokens where they speak of the assistant as a person
(«Chiedi a {assistant}», «Ciao, sono {assistant}»): :func:`named` fills only ``{assistant}`` and ``{g:…|…}``, and
``hestia_common.i18n.t`` calls it on every fixed text (docs/work/2026-11-16-name-everywhere). The clients call
themselves with it too (docs/work/2026-11-17-client-names); «Hestia» stays for releases, installer, file format.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

OWNER_NAME = "themis.personal.owner_name"
OWNER_CALL = "themis.personal.owner_call"
ASSISTANT_NAME = "themis.personal.assistant_name"
ASSISTANT_GENDER = "themis.personal.assistant_gender"
LANGUAGE = "themis.personal.language"



def _known_languages() -> tuple[dict[str, str], dict[str, str]]:
    """Every language with a ``locales/<code>/language.json`` (English first): code → English name, code → own name.
    Adding a language = adding its folder (docs/LANGUAGES.md «A new language»), no code change."""
    english: dict[str, str] = {}
    native: dict[str, str] = {}
    root = Path(__file__).resolve().parent / "locales"
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: (p.name != "en", p.name)):
        try:
            data = json.loads((d / "language.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        english[d.name] = str(data.get("english") or d.name)
        native[d.name] = str(data.get("native") or english[d.name])
    return english or {"en": "English"}, native or {"en": "English"}


# Language code → its English name, as the hidden prompt text says it (the setting's options use the own name).
LANGUAGES, NATIVE_NAMES = _known_languages()
DEFAULT_LANGUAGE = "it"

DEFAULT_NAME = "Hestia"
UNKNOWN_OWNER = "the person writing to you"
_GENDERED = re.compile(r"\{g:([^{}|]*)\|([^{}|]*)\}")
_MAX_NAME = 40


def _clean(value: Any) -> str:
    """A name as one short line: no line breaks or braces (it goes inside prompts)."""
    text = " ".join(str(value or "").replace("{", "").replace("}", "").split())
    return text[:_MAX_NAME].strip()


def read(get: Callable[[str], Any]) -> dict[str, str]:
    """``{assistant, gender, owner_name, owner, language}`` from a ``settings.get``-like reader (missing → defaults)."""
    def value(key: str) -> str:
        try:
            return _clean(get(key))
        except Exception:
            return ""
    owner_name = value(OWNER_NAME)
    return {"assistant": value(ASSISTANT_NAME) or DEFAULT_NAME,
            "gender": "he" if value(ASSISTANT_GENDER).lower() == "he" else "she",
            "owner_name": owner_name,
            "owner": value(OWNER_CALL) or owner_name,
            "language": language_code(value(LANGUAGE))}


def default() -> dict[str, str]:
    return {"assistant": DEFAULT_NAME, "gender": "she", "owner_name": "", "owner": "", "language": DEFAULT_LANGUAGE}


def language_code(value: Any) -> str:
    """A known language code (``it``, ``en``…); anything else → the default."""
    code = str(value or "").strip().lower()[:2]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def language_name(ident: dict[str, str] | None) -> str:
    """The owner's language in English, for hidden prompt text («Italian»)."""
    return LANGUAGES[language_code((ident or {}).get("language"))]


def owner_rule(ident: dict[str, str]) -> str:
    if ident.get("owner"):
        full = ident.get("owner_name") or ""
        also = f" (full name: {full})" if full and full != ident["owner"] else ""
        return f"Their name is {ident['owner']}{also}: use it now and then, not always."
    return "You do not know their name yet: if it is not in what you remember, ask at the first chance."


def render(text: str, ident: dict[str, str] | None = None) -> str:
    """Fill the identity tokens of ``text``. Other braces are left alone (templates are formatted after)."""
    raw = str(text or "")
    if "{" not in raw:
        return raw
    ident = ident or default()
    index = 2 if ident.get("gender") == "he" else 1
    raw = _GENDERED.sub(lambda m: m.group(index), raw)
    return (raw.replace("{assistant}", ident.get("assistant") or DEFAULT_NAME)
               .replace("{owner_rule}", owner_rule(ident))
               .replace("{owner_language}", language_name(ident))
               .replace("{owner}", ident.get("owner") or UNKNOWN_OWNER))


def named(text: str, ident: dict[str, str] | None = None) -> str:
    """A text people read with the assistant's name and gender filled (``{assistant}``, ``{g:her-form|his-form}``); every
    other brace stays for ``str.format``."""
    raw = str(text or "")
    if "{assistant}" not in raw and "{g:" not in raw:
        return raw
    ident = ident or default()
    index = 2 if ident.get("gender") == "he" else 1
    return _GENDERED.sub(lambda m: m.group(index), raw).replace("{assistant}", ident.get("assistant") or DEFAULT_NAME)

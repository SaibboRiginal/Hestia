"""Who the assistant is and whose it is (docs/work/2026-11-12-identita-e-proattivita).

Four personal settings owned by Themis (``settings_client.PERSONAL``): the owner's name, how to call him, the
assistant's name (default «Hestia») and whether it is a she or a he. Every prompt that speaks to the owner is
written once with tokens and rendered with :func:`render`:

- ``{assistant}``         → the assistant's name
- ``{owner}``             → how to call the owner (``the person writing to you`` while unknown)
- ``{owner_rule}``        → one sentence: his name, or «ask him» while unknown
- ``{g:amica|amico}``     → the first form for a she, the second for a he

A module reads the values with its own ``SettingsClient`` after ``follow_personal()``::

    ident = identity.read(settings.get)
    text = identity.render(TEMPLATE, ident)

The product, the modules and the repository keep the name Hestia: only the voice that talks to the owner changes.
"""
from __future__ import annotations

import re
from typing import Any, Callable

OWNER_NAME = "themis.personal.owner_name"
OWNER_CALL = "themis.personal.owner_call"
ASSISTANT_NAME = "themis.personal.assistant_name"
ASSISTANT_GENDER = "themis.personal.assistant_gender"

DEFAULT_NAME = "Hestia"
UNKNOWN_OWNER = "the person writing to you"
_GENDERED = re.compile(r"\{g:([^{}|]*)\|([^{}|]*)\}")
_MAX_NAME = 40


def _clean(value: Any) -> str:
    """A name as one short line: no line breaks or braces (it goes inside prompts)."""
    text = " ".join(str(value or "").replace("{", "").replace("}", "").split())
    return text[:_MAX_NAME].strip()


def read(get: Callable[[str], Any]) -> dict[str, str]:
    """``{assistant, gender, owner_name, owner}`` from a ``settings.get``-like reader (missing → defaults)."""
    def value(key: str) -> str:
        try:
            return _clean(get(key))
        except Exception:
            return ""
    owner_name = value(OWNER_NAME)
    return {"assistant": value(ASSISTANT_NAME) or DEFAULT_NAME,
            "gender": "lui" if value(ASSISTANT_GENDER).lower() == "lui" else "lei",
            "owner_name": owner_name,
            "owner": value(OWNER_CALL) or owner_name}


def default() -> dict[str, str]:
    return {"assistant": DEFAULT_NAME, "gender": "lei", "owner_name": "", "owner": ""}


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
    index = 2 if ident.get("gender") == "lui" else 1
    raw = _GENDERED.sub(lambda m: m.group(index), raw)
    return (raw.replace("{assistant}", ident.get("assistant") or DEFAULT_NAME)
               .replace("{owner_rule}", owner_rule(ident))
               .replace("{owner}", ident.get("owner") or UNKNOWN_OWNER))

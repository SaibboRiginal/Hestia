"""Search providers — what a module gives to the WebUI «Search everything» box (Ctrl+K or `/`).

Dossier ``docs/work/2026-11-27-webui-rethink`` piece 3. A module declares a provider in its plugin manifest
(``plugin_client.search(...)``) and answers ``GET <api_prefix>search?q=…&limit=…`` with ``{"items": [hit…]}``.
The WebUI asks every provider in parallel with a short timeout and shows each group as it arrives: a slow or
offline module never blocks the others.

    from hestia_common import search

    @app.get("/api/ui/search")
    def ui_search(q: str = "", limit: int = 5):
        return search.results(q, people, limit=limit, title=lambda p: p["name"], more=lambda p: [p.get("notes")],
                              hint=lambda p: p.get("relation", ""), icon="user", link=lambda p: f"person/{p['id']}")

A hit is ``{title, hint, icon, link}``: ``link`` is a page of the same module («person/12», «deadlines») or
``chat:<session_id>`` for a conversation. Titles and hints are the owner's own data (not translated); fixed words in
a hint go through ``tr``. Matching ignores case and accents, and every word of the query must appear.
"""
from __future__ import annotations

import unicodedata
from typing import Any, Callable, Iterable

MAX_LIMIT = 20

Getter = Callable[[Any], Any]


def fold(text: Any) -> str:
    """Lower case, no accents: «Café» → «cafe»."""
    s = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return "".join(c for c in s if not unicodedata.combining(c))


def words(q: str) -> list[str]:
    return [w for w in fold(q).split() if w]


def matches(q: str, *texts: Any) -> bool:
    """Every word of ``q`` appears somewhere in ``texts`` (an empty query matches nothing)."""
    ws = words(q)
    if not ws:
        return False
    hay = " ".join(fold(t) for t in _flat(texts))
    return all(w in hay for w in ws)


def rank(q: str, title: Any) -> int:
    """0 = the title starts with the query, 1 = the title has every word, 2 = only the other texts match."""
    t, f = fold(title), fold(q).strip()
    if f and t.startswith(f):
        return 0
    return 1 if all(w in t for w in words(q)) else 2


def hit(title: Any, *, hint: Any = "", icon: str = "", link: str = "") -> dict:
    return {"title": " ".join(str(title or "").split())[:120], "hint": " ".join(str(hint or "").split())[:120],
            "icon": icon, "link": link}


def results(q: str, rows: Iterable[Any], *, title: Getter, link: Getter | str, hint: Getter | str = "",
            icon: Getter | str = "", more: Getter | None = None, limit: int = 5) -> dict:
    """Filters ``rows`` by ``q`` (title + ``more`` texts), best titles first, and maps them to hits."""
    if not words(q):
        return {"items": []}
    found = []
    for i, row in enumerate(rows or []):
        name = title(row)
        extra = more(row) if more else ()
        if matches(q, name, extra):
            found.append((rank(q, name), i, row, name))
    found.sort(key=lambda x: (x[0], x[1]))
    cap = max(1, min(int(limit or 5), MAX_LIMIT))
    return {"items": [hit(name, hint=_get(hint, row), icon=_get(icon, row), link=_get(link, row))
                      for _, _, row, name in found[:cap]]}


def _get(spec: Getter | str, row: Any) -> Any:
    return spec(row) if callable(spec) else spec


def _flat(items: Iterable[Any]) -> Iterable[Any]:
    for x in items:
        if isinstance(x, (list, tuple, set)):
            yield from _flat(x)
        elif isinstance(x, dict):
            yield from _flat(x.values())
        elif x is not None:
            yield x

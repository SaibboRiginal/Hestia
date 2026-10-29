"""Daily recap pieces — what each module says about a day (dossier ``docs/work/2026-10-20-recap-giornaliero``).

The recap is one message a day («com'è andata, cosa c'è domani»). Every module that has something to say
exposes ``GET /api/module/recap?day=YYYY-MM-DD&next=YYYY-MM-DD`` and advertises it in its Hub registration
(``capabilities.recap_endpoint``). The answer is a **piece**: deterministic facts, fast, never an LLM call.
Athena collects the pieces, Oracle writes the text, Hermes delivers it. A new module joins the recap by
exposing the endpoint; nothing else changes.

    from hestia_common.recap import piece, item, recap_router, capabilities as recap_capabilities

    def _recap(day: date, nxt: date) -> dict:
        return piece("hercules", "Allenamento", icon="dumbbell", emoji="🏋️", order=30,
                     done=[item("Push A: 18 serie", tone="success")], next=[item("Pull B alle 18:30")])

    app.include_router(recap_router("hercules", _recap))
    caps.update(recap_capabilities())

``title`` is a generic word for the area («Allenamento», «Spese»): user texts never name modules.
``actions`` (optional, max 2): buttons the recap message carries for this module, Hermes action shape
(``{label, command}`` = a tool the client opens, or ``{label, service, path, method?, body?}``). They ride even on an
empty piece (e.g. «Racconta la giornata» after the evening recap, dossier ``2026-10-24-tutto-brainstorm-cindy`` B9).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable

logger = logging.getLogger("hestia_common.recap")

PATH = "/api/module/recap"
CAPABILITY = "recap_endpoint"
TONES = ("", "success", "warning", "danger", "info")


def capabilities(path: str = PATH) -> dict[str, str]:
    """Hub capability that puts the module in the recap."""
    return {CAPABILITY: path}


def item(text: str, *, tone: str = "", at: str = "") -> dict[str, str]:
    """One line of a piece. ``tone`` colours it in the WebUI (success/warning/danger/info); ``at`` = ISO time."""
    out = {"text": str(text or "").strip()}
    if tone in TONES and tone:
        out["tone"] = tone
    if at:
        out["at"] = str(at)
    return out


def _items(rows: Iterable[Any] | None) -> list[dict]:
    out: list[dict] = []
    for row in rows or []:
        if isinstance(row, str):
            row = item(row)
        if isinstance(row, dict) and str(row.get("text") or "").strip():
            out.append(row)
    return out


def piece(module: str, title: str, *, icon: str = "", emoji: str = "", order: int = 500,
          done: Iterable[Any] | None = None, missed: Iterable[Any] | None = None,
          next: Iterable[Any] | None = None, note: str = "",
          actions: Iterable[dict] | None = None) -> dict[str, Any]:
    """A module's piece of the recap. No line at all → ``{module, empty: true}`` (plus its ``actions``)."""
    lists = {"done": _items(done), "missed": _items(missed), "next": _items(next)}
    note = str(note or "").strip()
    acts = _actions(actions)
    if not any(lists.values()) and not note:
        return {**empty(module), **({"actions": acts} if acts else {})}
    out: dict[str, Any] = {"module": module, "title": title, "icon": icon, "emoji": emoji, "order": int(order)}
    out.update({k: v for k, v in lists.items() if v})
    if note:
        out["note"] = note
    if acts:
        out["actions"] = acts
    return out


def _actions(rows: Iterable[Any] | None) -> list[dict]:
    out = []
    for a in rows or []:
        if isinstance(a, dict) and str(a.get("label") or "").strip() and (a.get("command") or
                                                                           (a.get("service") and a.get("path"))):
            out.append(dict(a))
    return out[:2]


def empty(module: str) -> dict[str, Any]:
    return {"module": module, "empty": True}


def is_empty(p: Any) -> bool:
    if not isinstance(p, dict) or p.get("empty"):
        return True
    return not (p.get("done") or p.get("missed") or p.get("next") or str(p.get("note") or "").strip())


def parse_days(day: str | None = None, next: str | None = None, *, today: date | None = None) -> tuple[date, date]:
    """``day`` (default today, local time) and ``next`` (default the day after ``day``)."""
    base = today or datetime.now().date()
    d = date.fromisoformat(day) if day else base
    n = date.fromisoformat(next) if next else d + timedelta(days=1)
    return d, n


def hhmm(value: Any) -> str:
    """``2026-10-21T18:30:00+02:00`` → ``18:30`` (local wall time as written); '' when not a time."""
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if ts.tzinfo is not None:
        ts = ts.astimezone()
    return ts.strftime("%H:%M")


def recap_router(module: str, builder: Callable[[date, date], dict], path: str = PATH,
                 today: Callable[[], date] | None = None):
    """FastAPI router serving ``GET path?day=&next=`` from ``builder(day, next)``.
    ``today``: the module's own local day (its timezone) used when ``day`` is omitted; default the container's.
    A failing builder answers an empty piece (logged): the recap goes on without this module."""
    from fastapi import APIRouter, HTTPException

    router = APIRouter()

    @router.get(path)
    def module_recap(day: str = "", next: str = "") -> dict:
        try:
            d, n = parse_days(day or None, next or None, today=today() if today else None)
        except ValueError:
            raise HTTPException(status_code=400, detail="day/next must be YYYY-MM-DD")
        try:
            out = builder(d, n)
        except Exception as exc:
            logger.warning("[🔄] event=recap_piece_build_failed module=%s day=%s error=%s fallback=empty",
                           module, d, exc)
            return empty(module)
        return out if isinstance(out, dict) and out.get("module") else empty(module)

    return router

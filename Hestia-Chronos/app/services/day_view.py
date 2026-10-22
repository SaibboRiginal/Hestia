"""What a day looks like from Chronos — the user's calendar plus Hestia's own agenda.

Two users (docs/work/2026-10-20-recap-giornaliero):

- ``recap(day, nxt)``: the agenda piece of the daily recap — the user's events of ``day`` and ``nxt``, assistant
  tasks done / skipped / failed, jobs that failed (a job that works is not news);
- ``busy(start, end)``: the user's events overlapping a range, used by flexible jobs (§3.8) to fire around them.

The user's calendar = Archive calendar items of every source but ``hestia`` (synced Google/Outlook + local events).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from core import archive_client
from services import agenda as A

logger = logging.getLogger("hestia_chronos.day_view")

_MAX_LINES = 6


def _tz() -> ZoneInfo:
    return ZoneInfo(A._TZ_DEFAULT)


def _dt(value: Any) -> datetime | None:
    try:
        return A._parse(value, A._TZ_DEFAULT).astimezone(_tz())
    except (TypeError, ValueError):
        return None


def user_events(start: datetime, end: datetime) -> list[dict]:
    """The user's events overlapping [start, end), sorted, with parsed ``_start``/``_end`` (local time).
    Archive unreachable → [] (logged): the callers keep working without the calendar."""
    rows = archive_client.list_items(from_time=(start - timedelta(days=1)).isoformat(), to_time=end.isoformat(),
                                     limit=500)
    out = []
    for r in rows or []:
        if not isinstance(r, dict) or r.get("source") == A.SOURCE or r.get("status") == "cancelled":
            continue
        s = _dt(r.get("start_at"))
        if s is None:
            continue
        e = _dt(r.get("end_at")) or s
        if r.get("all_day") and e <= s:
            e = s + timedelta(days=1)
        if e < start or s >= end or (e == start and e > s):
            continue
        out.append({**r, "_start": s, "_end": e})
    return sorted(out, key=lambda r: r["_start"])


def busy(start: datetime, end: datetime) -> list[tuple[datetime, datetime, str]]:
    """Timed (not all-day) user events overlapping [start, end) as ``(start, end, title)``."""
    return [(r["_start"], r["_end"], str(r.get("title") or "impegno"))
            for r in user_events(start, end) if not r.get("all_day")]


def _event_line(r: dict) -> str:
    title = str(r.get("title") or "Impegno").strip()
    if r.get("all_day"):
        return f"{title} (tutto il giorno)"
    return f"{r['_start'].strftime('%H:%M')} {title}"


def _bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time(0, 0), tzinfo=_tz())
    return start, start + timedelta(days=1)


def _cap(lines: list[str]) -> list[str]:
    return lines if len(lines) <= _MAX_LINES else lines[:_MAX_LINES - 1] + [f"e altri {len(lines) - _MAX_LINES + 1}"]


def recap(day: date, nxt: date) -> dict:
    """Facts for the daily recap: plain data, no LLM."""
    done: list[dict] = []
    missed: list[dict] = []
    upcoming: list[dict] = []
    d0, d1 = _bounds(day)
    n0, n1 = _bounds(nxt)

    events = user_events(d0, d1)
    if events:
        done.append({"text": "Impegni: " + ", ".join(_cap([_event_line(r) for r in events]))})

    tasks_done, tasks_skipped, failed = [], [], []
    for o in A.agenda(d0, d1, include_done=True):
        if o["type"] == "task":
            run = o.get("run") or {}
            if o["skipped"]:
                tasks_skipped.append(o["title"])
            elif run and not run.get("ok"):
                failed.append(o["title"])
            elif run or o.get("status") == "completed":
                tasks_done.append(o["title"])
        elif o["type"] == "job" and (o.get("run") or {}).get("ok") is False:
            failed.append(o["title"])
    if tasks_done:
        done.append({"text": "Fatto: " + ", ".join(_cap(list(dict.fromkeys(tasks_done)))), "tone": "success"})
    if tasks_skipped:
        missed.append({"text": "Saltato: " + ", ".join(_cap(list(dict.fromkeys(tasks_skipped)))), "tone": "warning"})
    if failed:
        missed.append({"text": "Non riuscito: " + ", ".join(_cap(list(dict.fromkeys(failed)))), "tone": "danger"})

    for r in user_events(n0, n1):
        upcoming.append({"text": _event_line(r), "at": r["_start"].isoformat()})
    for o in A.agenda(n0, n1, type_="task"):
        if not o["skipped"]:
            s = _dt(o["start"])
            upcoming.append({"text": f"{s.strftime('%H:%M')} {o['title']}" if s else o["title"], "at": o["start"]})
    upcoming.sort(key=lambda x: x.get("at") or "")
    return {"done": done, "missed": missed, "next": upcoming[:_MAX_LINES]}

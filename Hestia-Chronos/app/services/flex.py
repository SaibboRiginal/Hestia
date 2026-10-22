"""Flexible activities — fire a job around the user's events (docs/work/2026-10-20-recap-giornaliero §3.8).

A rule may carry ``params.flex = {"earliest": "HH:MM", "latest": "HH:MM"}``. The nominal time (the one the user sees
and moves) stays the reference; when it falls inside one of the user's events, or closer than
``chronos.flex.gap_minutes`` to its start or end, the occurrence fires at the nearest free moment of the range:
after the event first, then before it, else at the end of the range. Deterministic, no LLM. A single occurrence the
user moved is a fixed time and never flexes.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Iterable

Busy = tuple[datetime, datetime, str]


def _hhmm(value: str) -> time | None:
    try:
        h, m = str(value or "").strip().split(":")[:2]
        return time(int(h) % 24, int(m) % 60)
    except (ValueError, TypeError):
        return None


def flex_range(nominal: datetime, flex: dict | None) -> tuple[datetime, datetime] | None:
    """[earliest, latest] on the nominal's local day (``latest`` before ``earliest`` = the next day).
    The nominal is always inside the range. Invalid / missing flex → None."""
    if not isinstance(flex, dict):
        return None
    lo, hi = _hhmm(flex.get("earliest")), _hhmm(flex.get("latest"))
    if lo is None and hi is None:
        return None
    day = nominal.date()
    start = datetime.combine(day, lo, tzinfo=nominal.tzinfo) if lo else nominal
    end = datetime.combine(day, hi, tzinfo=nominal.tzinfo) if hi else nominal
    if end < start:
        end += timedelta(days=1)
    if nominal < start and nominal + timedelta(days=1) <= end:
        start, end = start - timedelta(days=1), end - timedelta(days=1)
    return min(start, nominal), max(end, nominal)


def _clash(t: datetime, busy: list[Busy], gap: timedelta) -> Busy | None:
    for b in busy:
        if b[0] - gap < t < b[1] + gap:
            return b
    return None


def plan(nominal: datetime, flex: dict | None, busy: Iterable[Busy], gap: timedelta) -> tuple[datetime, str]:
    """→ (fire time, reason). Reason '' when the nominal time is kept."""
    rng = flex_range(nominal, flex)
    events = sorted(busy, key=lambda b: b[0])
    first = _clash(nominal, events, gap)
    if rng is None or first is None:
        return nominal, ""
    lo, hi = rng
    # after: walk past chained events
    t, last = nominal, first
    while (b := _clash(t, events, gap)) is not None:
        last, t = b, b[1] + gap
    if t <= hi:
        return t, f"dopo {last[2]}"
    # before: walk back past chained events
    t, last = nominal, first
    while (b := _clash(t, events, gap)) is not None:
        last, t = b, b[0] - gap
    if t >= lo:
        return t, f"prima di {last[2]}"
    return hi, "fine della fascia, sei impegnato"

"""Weekly coach planner — pure, deterministic placement (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §5.3).

Generic on purpose (core services stay generic): it reads only the contract fields of a need (kind, count, per,
minutes, min_minutes, days, fixed_dates, time_of_day, not_before/not_after, min_gap_days, not_same_day, with, tags,
priority). It never knows what a workout or a routine is.

    plan = plan_week(days, free, needs, keep=kept_items, cfg=cfg, fit=ask_module)

- ``days``   the dates to plan (today … end of the week), in order;
- ``free``   ``{date: [(start, end), …]}`` free intervals (aware datetimes), already without the user's events;
- ``needs``  validated needs, each with ``module`` added;
- ``keep``   items that stay where they are (done, moved by the user): they occupy time; ``counts: False``
             (done ones, already out of the module's count) do not reduce the need's count;
- ``avoid``  ``(module, need_id, date)`` the user skipped: that need does not come back on that day;
- ``fit``    ``(module, need_id, date, minutes) -> {ok, minutes, title, note} | None`` asks the module for a
             shorter variant when a day only has a smaller gap.

Same input → same output (stable sorts), so a re-plan only moves what has to move.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable

PRIORITY_ORDER = {"must": 0, "should": 1, "could": 2}
# Parts of the day (local wall time). "any" = the whole free window.
TIME_OF_DAY = {"morning": (time(6, 0), time(12, 0)), "midday": (time(11, 30), time(14, 30)),
               "afternoon": (time(13, 0), time(18, 30)), "evening": (time(17, 0), time(23, 0)),
               "any": (time(0, 0), time(23, 59))}
SLOT_TIME = {"morning": time(8, 0), "midday": time(13, 0), "afternoon": time(16, 0), "evening": time(21, 0),
             "any": time(12, 0)}
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


@dataclass
class PlannerConfig:
    max_blocks_per_day: int = 2
    max_minutes_per_day: int = 120
    buffer_minutes: int = 15


@dataclass
class _Day:
    day: date
    free: list[tuple[datetime, datetime]]
    blocks: list[tuple[datetime, datetime]] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)

    @property
    def block_count(self) -> int:
        return sum(1 for i in self.items if i["kind"] == "block")

    @property
    def block_minutes(self) -> int:
        return sum(int(i.get("minutes") or 0) for i in self.items if i["kind"] == "block")

    def tags(self) -> set[str]:
        out: set[str] = set()
        for i in self.items:
            out.update(i.get("tags") or [])
        return out


def free_intervals(day: date, start: time, end: time, busy: list[tuple[datetime, datetime]], tz,
                   buffer_minutes: int = 0) -> list[tuple[datetime, datetime]]:
    """Free time of ``day`` between ``start`` and ``end`` minus ``busy`` (each widened by the buffer)."""
    lo = datetime.combine(day, start, tzinfo=tz)
    hi = datetime.combine(day, end, tzinfo=tz) if end > start else datetime.combine(day + timedelta(days=1), end, tzinfo=tz)
    pad = timedelta(minutes=buffer_minutes)
    spans = sorted((s - pad, e + pad) for s, e in busy if e > lo and s < hi)
    out, cursor = [], lo
    for s, e in spans:
        if s > cursor:
            out.append((cursor, min(s, hi)))
        cursor = max(cursor, e)
        if cursor >= hi:
            break
    if cursor < hi:
        out.append((cursor, hi))
    return [(s, e) for s, e in out if e > s]


def _subtract(free: list[tuple[datetime, datetime]], taken: list[tuple[datetime, datetime]],
              pad: timedelta) -> list[tuple[datetime, datetime]]:
    out = list(free)
    for ts, te in taken:
        ts, te = ts - pad, te + pad
        nxt = []
        for s, e in out:
            if te <= s or ts >= e:
                nxt.append((s, e))
                continue
            if ts > s:
                nxt.append((s, ts))
            if te < e:
                nxt.append((te, e))
        out = nxt
    return out


def _window(need: dict, d: _Day, tz) -> tuple[datetime, datetime]:
    lo_t, hi_t = TIME_OF_DAY.get(need.get("time_of_day") or "any", TIME_OF_DAY["any"])
    if need.get("not_before"):
        lo_t = max(lo_t, time.fromisoformat(need["not_before"]))
    if need.get("not_after"):
        hi_t = min(hi_t, time.fromisoformat(need["not_after"]))
    return datetime.combine(d.day, lo_t, tzinfo=tz), datetime.combine(d.day, hi_t, tzinfo=tz)


def _gaps(need: dict, d: _Day, tz, pad: timedelta) -> list[tuple[datetime, datetime]]:
    lo, hi = _window(need, d, tz)
    out = []
    for s, e in _subtract(d.free, d.blocks, pad):
        s, e = max(s, lo), min(e, hi)
        if e > s:
            out.append((s, e))
    return out


def _clash(need: dict, d: _Day) -> str:
    """Why ``need`` cannot share the day (not_same_day, both directions), '' if it can."""
    mine = set(need.get("tags") or [])
    avoid = set(need.get("not_same_day") or [])
    for it in d.items:
        if avoid & set(it.get("tags") or []) or mine & set(it.get("not_same_day") or []):
            return it["title"]
    return ""


def _relation_ok(need: dict, d: _Day, days: dict[date, _Day]) -> bool:
    rel = need.get("with")
    if not rel:
        return True
    tag, how = rel["tag"], rel["relation"]
    if how == "day_after":
        prev = days.get(d.day - timedelta(days=1))
        return bool(prev and tag in prev.tags())
    return tag in d.tags()


def _sort_key(need: dict) -> tuple:
    return (1 if need.get("with") else 0, PRIORITY_ORDER.get(need.get("priority") or "should", 1),
            need.get("module") or "", need["id"])


def plan_week(days: list[date], free: dict[date, list[tuple[datetime, datetime]]], needs: list[dict], *,
              keep: list[dict] | None = None, avoid: set[tuple[str, str, date]] | None = None,
              cfg: PlannerConfig | None = None, tz=None,
              fit: Callable[[str, str, date, int], dict | None] | None = None) -> dict[str, Any]:
    cfg = cfg or PlannerConfig()
    pad = timedelta(minutes=max(0, cfg.buffer_minutes))
    grid = {d: _Day(d, sorted(free.get(d) or [])) for d in days}
    kept_by_need: dict[tuple[str, str], list[date]] = {}
    for k in sorted(keep or [], key=lambda i: (i.get("start") or "", i.get("need_id") or "")):
        d = k["date"] if isinstance(k["date"], date) else date.fromisoformat(str(k["date"])[:10])
        if k.get("counts", True):
            kept_by_need.setdefault((k.get("module") or "", k["need_id"]), []).append(d)
        if d in grid:
            grid[d].items.append({**k, "date": d})
            if k.get("kind") == "block" and k.get("start_dt") and k.get("end_dt"):
                grid[d].blocks.append((k["start_dt"], k["end_dt"]))
    items: list[dict] = []
    unplaced: list[dict] = []
    targets: list[dict] = []

    for n in sorted(needs, key=_sort_key):
        module = n.get("module") or ""
        if n["kind"] == "target":
            targets.append({"module": module, "need_id": n["id"], "title": n["title"], "value": n.get("value"),
                            "unit": n.get("unit"), "progress": n.get("progress"), "reason": n.get("reason"),
                            "link": n.get("link")})
            continue
        chosen = list(kept_by_need.get((module, n["id"]), []))
        allowed = [d for d in days if (module, n["id"], d) not in (avoid or set())
                   and (not n.get("days") or d.weekday() in n["days"])
                   and (not n.get("fixed_dates") or d.isoformat() in n["fixed_dates"])]
        if n.get("per") == "day":
            plans = [[d] for d in allowed if d not in chosen]
        else:
            plans = [allowed] * max(0, n["count"] - len(chosen))
        failed: list[str] = []
        for candidates in plans:
            pick = _choose(n, candidates, chosen, grid, cfg, pad, tz, fit, module)
            if pick is None:
                failed.append(_why(n, candidates, grid, cfg))
                continue
            items.append(pick)
            chosen.append(pick["date"])
            gd = grid[pick["date"]]
            gd.items.append(pick)
            if pick["kind"] == "block":
                gd.blocks.append((pick["start_dt"], pick["end_dt"]))
        if failed:
            unplaced.append({"module": module, "need_id": n["id"], "title": n["title"], "missing": len(failed),
                             "of": n["count"] if n.get("per") != "day" else len(plans),
                             "priority": n.get("priority"), "reason": failed[0], "link": n.get("link")})

    items.sort(key=lambda i: (i["start"], i["module"], i["need_id"]))
    for i in items:
        i.pop("start_dt", None)
        i.pop("end_dt", None)
    return {"items": items, "unplaced": unplaced, "targets": targets}


def _choose(n: dict, candidates: list[date], chosen: list[date], grid: dict[date, _Day], cfg: PlannerConfig,
            pad: timedelta, tz, fit, module: str) -> dict | None:
    """Best day for one occurrence: full length first; only if no day fits, a shorter variant from the module."""
    gap_days = int(n.get("min_gap_days") or 0)
    effort = next((int(t.split(":")[1]) for t in n.get("tags") or []
                   if t.startswith("effort:") and t.split(":")[1].isdigit()), 1)
    full: list[tuple] = []
    short: list[tuple] = []
    for d in candidates:
        gd = grid.get(d)
        if gd is None:
            continue
        if n.get("per") != "day" and d in chosen:
            continue
        if gap_days and any(abs((d - c).days) < gap_days for c in chosen if c != d):
            continue
        if _clash(n, gd) or not _relation_ok(n, gd, grid):
            continue
        spread = min((abs((d - c).days) for c in chosen if c != d), default=7)
        if n["kind"] == "slot":
            full.append(((-spread, d.toordinal()), d, None, 0))
            continue
        if gd.block_count >= cfg.max_blocks_per_day:
            continue
        room = cfg.max_minutes_per_day - gd.block_minutes
        gaps = _gaps(n, gd, tz, pad)
        longest = int(max(((e - s).total_seconds() // 60 for s, e in gaps), default=0))
        free_total = int(sum((e - s).total_seconds() // 60 for s, e in gaps))
        score = (-spread, -free_total * effort, d.toordinal())
        if longest >= n["minutes"] and room >= n["minutes"]:
            full.append((score, d, gaps, n["minutes"]))
        elif n["min_minutes"] < n["minutes"] and min(longest, room) >= n["min_minutes"]:
            short.append((score, d, gaps, min(longest, room)))
    if full:
        _score, d, gaps, minutes = min(full, key=lambda x: x[0])
        return _slot(n, d, tz, module) if n["kind"] == "slot" else _block(n, d, gaps, minutes, tz, module)
    for _score, d, gaps, minutes in sorted(short, key=lambda x: x[0]):
        variant = fit(module, n["id"], d, minutes) if fit else None
        if variant and variant.get("ok") and 0 < int(variant.get("minutes") or 0) <= minutes:
            out = _block(n, d, gaps, int(variant["minutes"]), tz, module)
            out["variant"] = {"minutes": int(variant["minutes"]), "title": variant.get("title") or "",
                              "note": variant.get("note") or "versione corta"}
            if variant.get("title"):
                out["title"] = variant["title"]
            return out
    return None


def _base(n: dict, d: date, module: str) -> dict:
    return {"module": module, "need_id": n["id"], "kind": n["kind"], "title": n["title"], "date": d,
            "tags": list(n.get("tags") or []), "not_same_day": list(n.get("not_same_day") or []),
            "reason": n.get("reason") or "", "link": n.get("link") or "", "priority": n.get("priority"),
            "time_of_day": n.get("time_of_day") or "any", "variant": None}


def _slot(n: dict, d: date, tz, module: str) -> dict:
    at = datetime.combine(d, SLOT_TIME.get(n.get("time_of_day") or "any", time(12, 0)), tzinfo=tz)
    return {**_base(n, d, module), "minutes": int(n.get("minutes") or 0), "start": at.isoformat(), "end": None}


def _block(n: dict, d: date, gaps: list[tuple[datetime, datetime]], minutes: int, tz, module: str) -> dict:
    need = timedelta(minutes=minutes)
    s, _e = next((s, e) for s, e in gaps if e - s >= need)
    if s.minute % 15:                                   # round up to the quarter when it still fits
        rounded = s + timedelta(minutes=15 - s.minute % 15)
        if any(rounded >= gs and rounded + need <= ge for gs, ge in gaps):
            s = rounded.replace(second=0, microsecond=0)
    e = s + need
    return {**_base(n, d, module), "minutes": minutes, "start": s.isoformat(), "end": e.isoformat(),
            "start_dt": s, "end_dt": e}


def _why(n: dict, candidates: list[date], grid: dict[date, _Day], cfg: PlannerConfig) -> str:
    if not candidates:
        return "nessun giorno possibile questa settimana"
    if n.get("with") and not any(_relation_ok(n, grid[d], grid) for d in candidates if d in grid):
        return f"nessun giorno con {n['with']['tag']}"
    if n["kind"] == "block":
        if all(grid[d].block_count >= cfg.max_blocks_per_day for d in candidates if d in grid):
            return "giorni già pieni"
        return f"mancano {n['min_minutes']}' liberi nei giorni possibili"
    return "vincoli con altre cose dello stesso giorno"

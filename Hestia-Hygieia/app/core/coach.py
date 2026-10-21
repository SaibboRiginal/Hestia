"""Hygieia as a coach of the weekly plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §7.2).

Routines are ``slot`` needs (a day and a part of the day, no reserved time): ``daily`` → every day, ``fixed_days`` →
those weekdays, ``target`` → what is left of the goal with the routine's spacing; ``as_needed`` and paused routines
need nothing. Conflicts (active families, explicit "not the same day") become ``not_same_day`` between routine tags,
so the week never puts them together. A routine with ``plan_with`` (a tag, e.g. ``workout``) lands only on days that
have it in the plan — supplements taken only on training days. Hygieia's own planner keeps deciding *today*.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from .planner import goal_state, period_next, period_start

SLOT_TOD = {"morning": "morning", "evening": "evening", "anytime": "any"}


class HygieiaCoach:
    def __init__(self, hygieia):
        self.h = hygieia

    def needs(self, start: date, end: date) -> dict:
        h = self.h
        day = h.day(start)
        days_in = (end - start).days
        out = []
        for r in h.items("routine"):
            if r.get("status") != "active":
                continue
            c = r.get("cadence") or {}
            mode = c.get("mode") or "target"
            if mode == "as_needed":
                continue
            plan = day.plan_routine(r)
            base = {"id": f"routine.{r['id']}", "title": r.get("name") or "Routine", "kind": "slot",
                    "time_of_day": SLOT_TOD.get(r.get("slot") or "anytime", "any"),
                    "minutes": int(plan.get("minutes") or 0), "tags": [f"routine.{r['id']}"],
                    "not_same_day": sorted(f"routine.{pid}" for pid in day.implicit_partners(r)),
                    "priority": "should", "reason": plan.get("hint") or "", "link": f"routine/{r['id']}"}
            if r.get("plan_with"):
                base["with"] = {"tag": str(r["plan_with"]), "relation": "same_day"}
            if mode == "daily":
                out.append({**base, "per": "day", "count": 1})
            elif mode == "fixed_days":
                out.append({**base, "per": "day", "count": 1, "days": list(c.get("days") or [])})
            else:
                g = goal_state(c, day.routine_days(r["id"]), start - timedelta(days=1), h.week_start())
                done_in_period = sum(1 for d in day.routine_days(r["id"])
                                     if period_start(start, c.get("per") or "week", h.week_start()) <= d < start)
                times = int(c.get("times") or 1)
                remaining = max(0, times - done_in_period)
                if (c.get("per") or "week") == "month":
                    p0 = period_start(start, "month", h.week_start())
                    weeks_left = max(1, math.ceil((period_next(p0, "month") - start).days / 7))
                    remaining = math.ceil(remaining / weeks_left)
                    gap = max(1, 30 // times)
                else:
                    gap = max(1, 7 // times)
                remaining = min(remaining, days_in)
                if remaining <= 0:
                    continue
                out.append({**base, "count": remaining, "min_gap_days": gap if remaining > 1 else 0,
                            "reason": g.get("hint") or base["reason"]})
        return {"state": h.summary()["text"][:300], "needs": out}

    def supplements(self) -> list[str]:
        """What I take (products of category ``integratore`` in use): information, nothing to log."""
        return [f"{p.get('brand') + ' ' if p.get('brand') else ''}{p['name']}" for p in self.h.items("product")
                if p.get("category") == "integratore" and p.get("status") == "in_use"]

    def review(self, start: date, end: date) -> dict:
        logs = [l for l in self.h.items("log") if l.get("routine_id") and start.isoformat() <= (l.get("date") or "") < end.isoformat()]
        done = sum(1 for l in logs if l.get("status") in ("done", "partial"))
        skipped = sum(1 for l in logs if l.get("status") == "skipped")
        return {"done": done, "missed": skipped, "notes": []}

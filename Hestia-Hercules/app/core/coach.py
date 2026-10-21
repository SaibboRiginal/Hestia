"""Hercules as a coach of the weekly plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §7.1).

Needs (``hestia_common.coach`` contract), always "still to do" from ``start``:
- weekly program → one ``workout.<weekday>`` block per program day left (that weekday only);
- otherwise a goal "N a settimana" (or a rotation program with a goal) → one ``workout`` block with ``count`` = what
  is left of the goal; no goal and no weekly program → no need (nothing to plan, no switch needed).
``fit`` = the time-limit rule of the adaptation engine (the short version of the next workout); ``placed`` keeps the
plan in memory so "next workout" and the reminder can say when; ``review`` counts sessions of a past week.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from . import adapt as adapt_engine
from . import records

TOD = ("morning", "midday", "afternoon", "evening", "any")


class HerculesCoach:
    def __init__(self, hercules):
        self.h = hercules
        self.placed: dict[str, Any] = {"week": None, "items": []}

    # ── settings ────────────────────────────────────────────────────────────
    def _tod(self) -> str:
        v = self.h.cfg("coach.time_of_day", "evening")
        return v if v in TOD else "evening"

    def _min_minutes(self) -> int:
        try:
            return max(10, int(self.h.cfg("coach.min_minutes", 30)))
        except (TypeError, ValueError):
            return 30

    # ── contract ────────────────────────────────────────────────────────────
    def _done_on(self, data, d: date, template_id: str | None = None) -> bool:
        return any(records.local_date(s.get("started_at"), self.h.tz) == d
                   and (template_id is None or s.get("template_id") == template_id) for s in data.sessions)

    def _plans(self) -> dict[str, dict]:
        return {p["date"]: p for p in self.h.store.items("plan")}

    def needs(self, start: date, end: date) -> dict:
        h = self.h
        h.store.refresh()
        data = h.data()
        summary = h.summary()
        flags = set(summary.get("flags") or [])
        effort = "effort:2" if "deload_suggested" in flags else "effort:3"
        templates = {t["id"]: t for t in h.store.items("template") if not t.get("archived")}
        plans = self._plans()
        tod, min_minutes = self._tod(), self._min_minutes()
        out: list[dict] = []
        reason_extra = " · settimana di scarico consigliata" if "deload_suggested" in flags else ""
        prog = h.active_program()
        if prog and prog.get("mode") == "weekly" and prog.get("days"):
            d = start
            while d < end:
                p = plans.get(d.isoformat())
                for day in prog["days"]:
                    t = templates.get(day.get("template_id"))
                    if day.get("weekday") != d.weekday() or not t:
                        continue
                    if (p and p.get("status") in ("skipped", "moved")) or self._done_on(data, d, t["id"]):
                        continue
                    minutes = self._minutes(t)
                    out.append({"id": f"workout.{d.weekday()}", "title": t["name"], "kind": "block", "count": 1,
                                "minutes": minutes, "min_minutes": min(min_minutes, minutes), "days": [d.weekday()],
                                "time_of_day": tod, "tags": ["workout", effort, *self._muscle_tags(t)],
                                "priority": "should", "reason": f"in programma {h_weekday(d)}{reason_extra}",
                                "link": "oggi"})
                d += timedelta(days=1)
        else:
            goal = next((g for g in h.goals() if (g.get("scope") or "any") == "any"), None)
            if goal:
                prog_ = goal["progress"]
                remaining = int(prog_.get("remaining") or 0)
                if prog_.get("per") == "month":
                    weeks_left = max(1, math.ceil((prog_.get("days_left") or 7) / 7))
                    remaining = math.ceil(remaining / weeks_left)
                if prog_.get("per") == "day":
                    remaining = 0 if prog_.get("met") else 1
                remaining = min(remaining, (end - start).days)
                nxt = (summary.get("next") or {}).get("template")
                if remaining > 0:
                    minutes = self._minutes(nxt) if nxt else 60
                    out.append({"id": "workout", "title": "Allenamento", "kind": "block", "count": remaining,
                                "per": "day" if prog_.get("per") == "day" else "week",
                                "minutes": minutes, "min_minutes": min(min_minutes, minutes), "time_of_day": tod,
                                "min_gap_days": 2 if remaining <= 3 else 1,
                                "tags": ["workout", effort], "priority": "should",
                                "reason": f"{prog_.get('hint')}" + (f" · prossima: {nxt['name']}" if nxt else "")
                                          + reason_extra, "link": "oggi"})
        state = " · ".join((summary.get("lines") or [])[:2])
        return {"state": state, "needs": out}

    def _minutes(self, template: dict | None) -> int:
        if not template:
            return 60
        plan = self.h._plan_from_template(template, suggest=False)
        return max(20, adapt_engine.estimate_minutes(plan) or int(template.get("estimated_minutes") or 60))

    @staticmethod
    def _muscle_tags(template: dict) -> list[str]:
        name = (template.get("name") or "").lower()
        return [t for t, words in (("legs", ("gamb", "leg", "squat")), ("push", ("push", "spinta", "petto")),
                                   ("pull", ("pull", "trazion", "schiena"))) if any(w in name for w in words)]

    def fit(self, need_id: str, day: date, minutes: int) -> dict:
        """Short version: the adaptation engine's time-limit rule on the workout of that day."""
        h = self.h
        t = (h.next_workout(day) or {}).get("template")
        if not t:
            return {"ok": False}
        catalog_map = {e["id"]: e for e in h.store.items("exercise")}
        cfg = {"default_rest": int(h.cfg("rest.default_seconds", 90))}
        res = adapt_engine.adapt(h._plan_from_template(t, suggest=False), catalog_map, {"time_minutes": minutes},
                                 intent="shorter", cfg=cfg, increments=h.increments())
        after = int(res.get("minutes_after") or 0)
        if not after or after > minutes:
            return {"ok": False}
        return {"ok": True, "minutes": after, "title": f"{t['name']} (corto)",
                "note": f"versione corta {after}' invece di {res.get('minutes_before')}'"}

    def on_placed(self, week: str, items: list[dict]) -> None:
        self.placed = {"week": week, "items": [i for i in items if i.get("status") == "planned"]}

    def next_planned(self, now: datetime | None = None) -> dict | None:
        """The next workout in the weekly plan (for the summary and the reminder)."""
        now = now or datetime.now(self.h.tz)
        upcoming = []
        for i in self.placed.get("items") or []:
            try:
                at = datetime.fromisoformat(str(i.get("start_at")).replace("Z", "+00:00")).astimezone(self.h.tz)
            except ValueError:
                continue
            if at.date() >= now.date():
                upcoming.append((at, i))
        if not upcoming:
            return None
        at, item = min(upcoming, key=lambda x: x[0])
        return {"at": at.isoformat(), "label": f"{h_weekday(at.date(), now.date())} {at:%H:%M}", "key": item.get("key")}

    def review(self, start: date, end: date) -> dict:
        h = self.h
        data = h.data()
        done = [s for s in data.sessions if start <= (records.local_date(s.get("started_at"), h.tz) or date.min) < end
                and s.get("status") in (None, "done")]
        skipped = [p for p in h.store.items("plan") if p.get("status") == "skipped" and start.isoformat() <= p["date"] < end.isoformat()]
        goal = next((g for g in h.store.items("goal") if g.get("active", True) and (g.get("scope") or "any") == "any"
                     and (g.get("per") or "week") == "week"), None)
        notes = []
        if goal:
            notes.append(f"obiettivo {goal.get('times')} a settimana: {len(done)} fatti")
        flags = set(h.summary().get("flags") or [])
        if "deload_suggested" in flags:
            notes.append("energia bassa spesso: scarico consigliato")
        if "stall" in flags:
            notes.append("qualche esercizio fermo")
        target = goal.get("times") if goal else None
        return {"done": len(done), "missed": len(skipped), "notes": notes,
                "adherence": round(len(done) / target, 2) if target else None}


def h_weekday(d: date, today: date | None = None) -> str:
    from .service import WEEKDAYS
    today = today or date.today()
    if d == today:
        return "oggi"
    if d == today + timedelta(days=1):
        return "domani"
    return WEEKDAYS[d.weekday()]

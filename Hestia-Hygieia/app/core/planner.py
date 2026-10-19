"""Planner (SPEC §3.4, §4): routines and steps are goals, not calendars.

A cadence is ``{mode, times, per, days}``:
- ``daily``      every day (mandatory)
- ``fixed_days`` mandatory on ``days`` (0 = Monday … 6 = Sunday)
- ``target``     at least ``times`` per ``per`` (week | month)
- ``as_needed``  no goal, only logged
Routine constraints: ``max_per_day`` (default 1), ``min_gap_hours``, ``not_same_day_as`` (routine ids). Active
conflicts (retinoids vs acids…) add not-same-day pairs automatically. Nothing is ever overdue forever: a missed
period just starts a new one.

States: ``done`` (today) · ``due`` (behind the goal / mandatory today) · ``suggested`` (goal not met, good day) ·
``wait`` (goal not met, done recently) · ``ok`` (goal met) · ``off`` (fixed day not today) · ``rest`` (as needed) ·
``blocked`` (a constraint says not today; ``reason`` tells which).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .catalog import CONFLICTS, families

DONE_STATUSES = ("done", "partial")
PER_LABEL = {"day": "oggi", "week": "sett.", "month": "mese"}
ACTIVE_STATES = ("due", "suggested")


def period_start(d: date, per: str, week_start: int = 0) -> date:
    if per == "month":
        return d.replace(day=1)
    if per == "day":
        return d
    return d - timedelta(days=(d.weekday() - week_start) % 7)


def period_next(start: date, per: str) -> date:
    if per == "month":
        days = calendar.monthrange(start.year, start.month)[1]
        return start + timedelta(days=days)
    if per == "day":
        return start + timedelta(days=1)
    return start + timedelta(days=7)


def norm_cadence(c: dict | None, default_mode: str = "target") -> dict:
    c = dict(c or {})
    mode = c.get("mode") or default_mode
    if mode not in ("daily", "fixed_days", "target", "as_needed"):
        mode = default_mode
    out = {"mode": mode}
    if mode == "target":
        out["times"] = max(1, int(c.get("times") or 1))
        out["per"] = c.get("per") if c.get("per") in ("week", "month") else "week"
    if mode == "fixed_days":
        out["days"] = sorted({int(x) for x in (c.get("days") or []) if str(x).lstrip("-").isdigit() and 0 <= int(x) <= 6})
    return out


def cadence_label(c: dict | None) -> str:
    c = norm_cadence(c)
    m = c["mode"]
    if m == "daily":
        return "Ogni giorno"
    if m == "as_needed":
        return "Quando capita"
    if m == "fixed_days":
        names = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
        return "Ogni " + ", ".join(names[d] for d in c["days"]) if c["days"] else "Giorni fissi"
    t = c["times"]
    return f"Almeno {t} {'volta' if t == 1 else 'volte'} a{'l mese' if c['per'] == 'month' else ' settimana'}"


def goal_state(cadence: dict | None, done_days: list[date], today: date, week_start: int = 0,
               done_today: int = 0) -> dict:
    """Where a goal stands today from the local days it was done (one entry per log)."""
    c = norm_cadence(cadence)
    mode = c["mode"]
    last = max(done_days) if done_days else None
    since = (today - last).days if last else None
    base = {"mode": mode, "label": cadence_label(c), "last_done": last.isoformat() if last else None,
            "days_since": since, "done_today": done_today}
    if mode == "daily":
        return {**base, "state": "done" if done_today else "due", "done": done_today, "times": 1, "per": "day",
                "hint": "fatta oggi" if done_today else "da fare oggi", "behind": not done_today}
    if mode == "fixed_days":
        today_on = today.weekday() in c["days"]
        st = "done" if done_today else ("due" if today_on else "off")
        nxt = next(((today + timedelta(days=i)) for i in range(1, 8) if (today + timedelta(days=i)).weekday() in c["days"]), None)
        return {**base, "state": st, "done": done_today, "times": 1, "per": "day", "behind": st == "due",
                "hint": "fatta oggi" if done_today else ("oggi" if today_on else (f"prossima {nxt.strftime('%d/%m')}" if nxt else ""))}
    if mode == "as_needed":
        return {**base, "state": "done" if done_today else "rest", "done": done_today, "times": 0, "per": "",
                "hint": "fatta oggi" if done_today else (f"ultima {since} g fa" if since is not None else "mai fatta"),
                "behind": False}
    per, times = c["per"], c["times"]
    start = period_start(today, per, week_start)
    done = sum(1 for d in done_days if start <= d <= today)
    days_left = (period_next(start, per) - today).days          # today included
    remaining = max(0, times - done)
    period_days = (period_next(start, per) - start).days
    gap = max(1, period_days // max(1, times))                   # 3/week → every other day, 1/week → a week
    behind = remaining > 0 and remaining * 2 - 1 >= days_left
    if done_today:
        st = "done"
    elif remaining == 0:
        st = "ok"
    elif behind:
        st = "due"
    elif since is None or since >= gap:
        st = "suggested"
    else:
        st = "wait"
    hint = f"{done}/{times} {PER_LABEL[per]}"
    return {**base, "state": st, "done": done, "times": times, "per": per, "remaining": remaining,
            "days_left": days_left, "behind": behind, "hint": hint}


def conflict_notes(fam_a: set[str], fam_b: set[str], custom: list[dict] | None = None) -> list[str]:
    notes = []
    for rule in list(CONFLICTS) + list(custom or []):
        a, b = rule.get("a"), rule.get("b")
        if (a in fam_a and b in fam_b) or (b in fam_a and a in fam_b):
            notes.append(rule.get("note") or f"{a} e {b} non nello stesso giorno")
    return notes


class Day:
    """Everything the planner needs for one local day, prepared once."""

    def __init__(self, day: date, routines: list[dict], logs: list[dict], products: dict[str, dict],
                 week_start: int = 0, custom_actives: list[dict] | None = None, custom_conflicts: list[dict] | None = None,
                 now: datetime | None = None, local_date: Callable[[Any], date | None] | None = None):
        self.day = day
        self.routines = {r["id"]: r for r in routines}
        self.products = products
        self.week_start = week_start
        self.custom_actives = custom_actives or []
        self.custom_conflicts = custom_conflicts or []
        self.now = now
        self.local_date = local_date
        self.logs = [l for l in logs if l.get("date") and l["date"] <= day.isoformat()]
        self.today_logs = [l for l in self.logs if l["date"] == day.isoformat() and l.get("status") in DONE_STATUSES]

    # ── products/actives ───────────────────────────────────────────────────
    def product_families(self, product_id: str | None) -> set[str]:
        p = self.products.get(product_id or "") or {}
        return families([a.get("name") if isinstance(a, dict) else a for a in p.get("actives") or []], self.custom_actives)

    def step_families(self, step: dict) -> set[str]:
        return self.product_families(step.get("product_id"))

    def used_today(self, exclude_routine: str | None = None) -> dict[str, str]:
        """family → label of what used it today (other routines' done steps and ad-hoc uses)."""
        out: dict[str, str] = {}
        for l in self.today_logs:
            if exclude_routine and l.get("routine_id") == exclude_routine:
                continue
            r = self.routines.get(l.get("routine_id") or "")
            for s in l.get("steps") or []:
                if not s.get("done"):
                    continue
                p = self.products.get(s.get("product_id") or "") or {}
                for f in self.product_families(s.get("product_id")):
                    out.setdefault(f, p.get("name") or (r or {}).get("name") or "un prodotto")
        return out

    # ── per routine ────────────────────────────────────────────────────────
    def routine_days(self, rid: str) -> list[date]:
        return [date.fromisoformat(l["date"]) for l in self.logs
                if l.get("routine_id") == rid and l.get("status") in DONE_STATUSES]

    def step_days(self, rid: str, step_id: str) -> list[date]:
        out = []
        for l in self.logs:
            if l.get("routine_id") != rid or l.get("status") not in DONE_STATUSES:
                continue
            if any(s.get("step_id") == step_id and s.get("done") for s in l.get("steps") or []):
                out.append(date.fromisoformat(l["date"]))
        return out

    def core_families(self, r: dict) -> set[str]:
        """Actives of the steps that run every time (no own cadence): they define routine-level conflicts."""
        fam: set[str] = set()
        for s in r.get("steps") or []:
            if not s.get("cadence"):
                fam |= self.step_families(s)
        return fam

    def implicit_partners(self, r: dict) -> dict[str, str]:
        """Other routines that must not share the day with ``r`` → reason."""
        out = {}
        for pid in r.get("not_same_day_as") or []:
            other = self.routines.get(pid)
            if other:
                out[pid] = f"non oggi: {other.get('name')}"
        mine = self.core_families(r)
        if mine:
            for oid, other in self.routines.items():
                if oid == r["id"] or other.get("status") != "active":
                    continue
                notes = conflict_notes(mine, self.core_families(other), self.custom_conflicts)
                if notes:
                    out.setdefault(oid, f"non oggi: {other.get('name')} ({notes[0]})")
        for oid, other in self.routines.items():       # symmetric explicit pairs
            if r["id"] in (other.get("not_same_day_as") or []):
                out.setdefault(oid, f"non oggi: {other.get('name')}")
        return out

    def plan_routine(self, r: dict) -> dict:
        rid = r["id"]
        days = self.routine_days(rid)
        today_logs = [l for l in self.today_logs if l.get("routine_id") == rid]
        g = goal_state(r.get("cadence"), days, self.day, self.week_start, done_today=len(today_logs))
        state, reason = g["state"], ""
        if r.get("status") == "paused":
            state, reason = "paused", "in pausa"
        elif state != "done":
            done_ids = {l.get("routine_id") for l in self.today_logs}
            for oid, why in self.implicit_partners(r).items():
                if oid in done_ids:
                    state, reason = "blocked", why
                    break
            gap = r.get("min_gap_hours")
            if state != "blocked" and gap and self.now is not None:
                last = max((l.get("done_at") or "" for l in self.logs if l.get("routine_id") == rid
                            and l.get("status") in DONE_STATUSES), default="")
                if last:
                    try:
                        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        hours = (self.now - last_dt).total_seconds() / 3600
                        if hours < float(gap):
                            state, reason = "blocked", f"fatta {int(hours)} h fa (minimo {int(gap)} h)"
                    except ValueError:
                        pass
        steps = self.plan_steps(r, today_logs[-1] if today_logs else None)
        warnings = sorted({w for s in steps for w in s.get("warnings", [])})
        return {"routine_id": rid, "name": r.get("name"), "slot": r.get("slot") or "anytime", "areas": r.get("areas") or [],
                "state": state, "reason": reason, "goal": g, "hint": g.get("hint", ""), "favorite": bool(r.get("favorite")),
                "order": r.get("order") or 0, "icon": r.get("icon") or "", "color": r.get("color") or "",
                "reminder": bool(r.get("reminder")), "steps": steps, "warnings": warnings,
                "log_id": today_logs[-1]["id"] if today_logs else None,
                "minutes": round(sum(int(s.get("wait_seconds") or 0) for s in steps if s["include"]) / 60
                                 + len([s for s in steps if s["include"]]) * 1)}

    def plan_steps(self, r: dict, log: dict | None) -> list[dict]:
        rid = r["id"]
        steps = sorted(r.get("steps") or [], key=lambda s: s.get("order") or 0)
        used = self.used_today(exclude_routine=rid)
        logged = {s.get("step_id"): s for s in (log or {}).get("steps") or []}
        evaluated: dict[str, dict] = {}
        today_iso = self.day.isoformat()
        for s in steps:                          # paused for a while ("niente retinolo per una settimana")
            if (s.get("paused_until") or "") > today_iso:
                until = s["paused_until"]
                evaluated[s["id"]] = {"include": False, "state": "paused", "reason": f"in pausa fino al {until[8:10]}/{until[5:7]}",
                                      "goal": None}
        # steps with their own goal first: what is already done today is a fact, then the most behind wins the conflicts
        order = {"done": -1, "due": 0, "suggested": 1, "wait": 2, "ok": 3, "off": 4, "rest": 5}
        with_goal = [s for s in steps if s.get("cadence") and s["id"] not in evaluated]
        goals = {s["id"]: goal_state(s["cadence"], self.step_days(rid, s["id"]), self.day, self.week_start,
                                     done_today=1 if logged.get(s["id"], {}).get("done") else 0) for s in with_goal}
        chosen: dict[str, set[str]] = {}         # step id → families, of the steps included so far
        for s in sorted(with_goal, key=lambda s: (order.get(goals[s["id"]]["state"], 9), s.get("order") or 0)):
            g = goals[s["id"]]
            fam = self.step_families(s)
            include, reason = g["state"] in ACTIVE_STATES or g["state"] == "done", ""
            if include and g["state"] != "done":
                clash = [used[f] for f in used if conflict_notes(fam, {f}, self.custom_conflicts)]
                notes = [n for other in chosen.values() for n in conflict_notes(fam, other, self.custom_conflicts)]
                notes += conflict_notes(fam, set(used), self.custom_conflicts)
                partner = [o for o in s.get("not_same_day_as") or [] if o in chosen or o in {l.get("routine_id") for l in self.today_logs}]
                if notes or partner:
                    include = False
                    names = [self._step_name(next((x for x in steps if x["id"] == p), None)) for p in chosen
                             if conflict_notes(fam, chosen[p], self.custom_conflicts)]
                    reason = "non oggi: " + (names[0] if names else (clash[0] if clash else "conflitto"))
            elif not include:
                reason = {"ok": "obiettivo raggiunto", "wait": "fatto da poco", "off": "non è il giorno",
                          "rest": "quando serve"}.get(g["state"], "")
            if include:
                chosen[s["id"]] = fam
            evaluated[s["id"]] = {"include": include, "state": g["state"] if include or not reason.startswith("non oggi")
                                  else "blocked", "reason": reason, "goal": g}
        out = []
        for s in steps:
            p = self.products.get(s.get("product_id") or "") or None
            ev = evaluated.get(s["id"]) or {"include": True, "state": "always", "reason": "", "goal": None}
            warnings = []
            if p and p.get("status") in ("finished", "discarded"):
                warnings.append(f"{p.get('name')} è finito")
            if s.get("product_id") and not p:
                warnings.append("prodotto non trovato")
            if ev["include"] and not s.get("cadence"):
                fam = self.step_families(s)
                for other in chosen.values():
                    for n in conflict_notes(fam, other, self.custom_conflicts):
                        warnings.append(n)
            done = logged.get(s["id"])
            out.append({"step_id": s["id"], "order": s.get("order") or 0, "label": self._step_name(s),
                        "product": {"id": p["id"], "name": p.get("name"), "brand": p.get("brand"),
                                    "status": p.get("status"), "favorite": bool(p.get("favorite"))} if p else None,
                        "amount": s.get("amount") or "", "wait_seconds": int(s.get("wait_seconds") or 0),
                        "optional": bool(s.get("optional")), "note": s.get("note") or "",
                        "cadence": norm_cadence(s["cadence"]) if s.get("cadence") else None,
                        "include": ev["include"], "state": ev["state"], "reason": ev["reason"],
                        "hint": (ev["goal"] or {}).get("hint", "") if s.get("cadence") else "",
                        "done": bool(done and done.get("done")) if done else None, "warnings": warnings})
        return out

    def _step_name(self, s: dict | None) -> str:
        if not s:
            return ""
        p = self.products.get(s.get("product_id") or "") or {}
        return s.get("label") or p.get("name") or "passo"

    def plan(self, include_inactive: bool = False) -> list[dict]:
        out = []
        for r in self.routines.values():
            if r.get("status") == "archived" or (r.get("status") == "paused" and not include_inactive):
                continue
            out.append(self.plan_routine(r))
        slot_order = {"morning": 0, "anytime": 1, "evening": 2}
        out.sort(key=lambda p: (slot_order.get(p["slot"], 1), p["order"], p["name"] or ""))
        return out

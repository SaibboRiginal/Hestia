"""Records and statistics — pure functions over sessions, sets and exercises (SPEC §4.5).

Only completed, non-discarded sessions count. Warm-up sets never count for records or volume.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from .catalog import MUSCLE_GROUPS, group_of
from .store import parse_dt

WORKING = {"normal", "drop", "failure"}
REP_MAXES = (1, 3, 5, 8, 10, 12)
E1RM_MAX_REPS = 15


def e1rm(weight: float | None, reps: int | None, formula: str = "epley") -> float | None:
    if weight is None or not reps or reps <= 0 or weight <= 0 or reps > E1RM_MAX_REPS:
        return None
    if reps == 1:
        return round(weight, 2)
    if formula == "brzycki":
        return round(weight * 36 / (37 - reps), 2)
    return round(weight * (1 + reps / 30), 2)


def load_of(s: dict, exercise: dict | None, bodyweight: float | None) -> float | None:
    """Kilos actually moved by one set, by exercise kind (bodyweight ones need the bodyweight)."""
    kind = (exercise or {}).get("kind", "weight_reps")
    w = s.get("weight_kg")
    if kind in ("weight_reps", "weight_duration"):
        return w
    if kind == "weighted_bodyweight":
        return (bodyweight or 0) + (w or 0) if bodyweight else w
    if kind == "assisted_bodyweight":
        return max(0.0, bodyweight - (w or 0)) if bodyweight else None
    if kind == "bodyweight_reps":
        return bodyweight
    return None


def is_working(s: dict) -> bool:
    return s.get("completed", True) and (s.get("type") or "normal") in WORKING


def is_hard(s: dict) -> bool:
    """A hard set: working, done, not obviously easy (RPE ≥ 6 when given)."""
    rpe = s.get("rpe")
    return is_working(s) and (rpe is None or rpe >= 6) and (s.get("reps") or s.get("duration_s"))


class Data:
    """Indexes the store once per revision: done sessions by time, sets by session and exercise."""

    def __init__(self, sessions: list[dict], sets: list[dict], exercises: list[dict], measurements: list[dict]):
        self.exercises = {e["id"]: e for e in exercises}
        self.sessions = sorted((s for s in sessions if s.get("status") == "done"),
                               key=lambda s: s.get("started_at") or "")
        self.session_by_id = {s["id"]: s for s in sessions}
        done_ids = {s["id"] for s in self.sessions}
        self.sets_by_session: dict[str, list[dict]] = defaultdict(list)
        self.sets_by_exercise: dict[str, list[dict]] = defaultdict(list)
        for st in sorted(sets, key=lambda x: (x.get("session_at") or "", x.get("position") or 0)):
            if st.get("session_id") in done_ids:
                self.sets_by_session[st["session_id"]].append(st)
                self.sets_by_exercise[st["exercise_id"]].append(st)
        self.bodyweights = sorted(((parse_dt(m.get("taken_at")), m["value"]) for m in measurements
                                   if m.get("kind") == "bodyweight" and parse_dt(m.get("taken_at"))),
                                  key=lambda x: x[0])

    def bodyweight_at(self, when: Any) -> float | None:
        """Session bodyweight, else the last measurement before it, else the first after it."""
        sess = None
        if isinstance(when, dict):
            sess, when = when, when.get("started_at")
        if sess and sess.get("bodyweight_kg"):
            return sess["bodyweight_kg"]
        t = parse_dt(when)
        if not self.bodyweights:
            return None
        if t is None:
            return self.bodyweights[-1][1]
        before = [v for d, v in self.bodyweights if d <= t]
        return before[-1] if before else self.bodyweights[0][1]

    def load(self, st: dict) -> float | None:
        sess = self.session_by_id.get(st.get("session_id")) or {}
        return load_of(st, self.exercises.get(st.get("exercise_id")), self.bodyweight_at(sess))


# ── per exercise ─────────────────────────────────────────────────────────────

def exposures(data: Data, exercise_id: str, formula: str = "epley") -> list[dict]:
    """One entry per session where the exercise was trained (oldest first)."""
    by_session: dict[str, list[dict]] = defaultdict(list)
    for st in data.sets_by_exercise.get(exercise_id, []):
        by_session[st["session_id"]].append(st)
    out = []
    for sess in data.sessions:
        sets = by_session.get(sess["id"])
        if not sets:
            continue
        work = [s for s in sets if is_working(s)]
        loads = [(data.load(s), s) for s in work]
        top = max(((l, s) for l, s in loads if l is not None), key=lambda x: (x[0], x[1].get("reps") or 0), default=None)
        e1 = [e1rm(l, s.get("reps"), formula) for l, s in loads]
        e1 = [x for x in e1 if x]
        out.append({"session_id": sess["id"], "date": sess.get("started_at"), "name": sess.get("name"),
                    "sets": len(work), "reps": sum(s.get("reps") or 0 for s in work),
                    "volume": round(sum((l or 0) * (s.get("reps") or 0) for l, s in loads), 1),
                    "top_weight": top[0] if top else None, "top_reps": top[1].get("reps") if top else None,
                    "best_e1rm": max(e1) if e1 else None,
                    "max_reps": max((s.get("reps") or 0 for s in work), default=0),
                    "duration_s": max((s.get("duration_s") or 0 for s in work), default=0),
                    "detail": [{"weight_kg": s.get("weight_kg"), "reps": s.get("reps"), "rpe": s.get("rpe"),
                                "type": s.get("type"), "duration_s": s.get("duration_s")} for s in sets]})
    return out


def exercise_records(data: Data, exercise_id: str, formula: str = "epley", *, before: str | None = None) -> dict:
    """Best values for one exercise (optionally only sessions before a date, to spot new PRs)."""
    rec: dict[str, Any] = {"heaviest": None, "best_e1rm": None, "best_set_volume": None, "best_session_volume": None,
                           "most_reps": None, "longest_s": None, "rep_max": {}}
    for exp in exposures(data, exercise_id, formula):
        if before and (exp["date"] or "") >= before:
            continue
        sess_vol = exp["volume"]
        if sess_vol and (rec["best_session_volume"] is None or sess_vol > rec["best_session_volume"]["value"]):
            rec["best_session_volume"] = {"value": sess_vol, "date": exp["date"], "session_id": exp["session_id"]}
    for st in data.sets_by_exercise.get(exercise_id, []):
        if not is_working(st):
            continue
        if before and (st.get("session_at") or "") >= before:
            continue
        when = {"date": st.get("session_at"), "session_id": st.get("session_id"), "set_id": st.get("id")}
        load, reps = data.load(st), st.get("reps") or 0
        if load is not None and load > 0:
            if rec["heaviest"] is None or load > rec["heaviest"]["value"]:
                rec["heaviest"] = {"value": load, "reps": reps, **when}
            est = e1rm(load, reps, formula)
            if est and (rec["best_e1rm"] is None or est > rec["best_e1rm"]["value"]):
                rec["best_e1rm"] = {"value": est, "weight": load, "reps": reps, **when}
            vol = round(load * reps, 1)
            if reps and (rec["best_set_volume"] is None or vol > rec["best_set_volume"]["value"]):
                rec["best_set_volume"] = {"value": vol, "weight": load, "reps": reps, **when}
            for n in REP_MAXES:
                if reps >= n and (n not in rec["rep_max"] or load > rec["rep_max"][n]["value"]):
                    rec["rep_max"][n] = {"value": load, "reps": reps, **when}
        if reps and (rec["most_reps"] is None or reps > rec["most_reps"]["value"]):
            rec["most_reps"] = {"value": reps, "weight": load, **when}
        dur = st.get("duration_s") or 0
        if dur and (rec["longest_s"] is None or dur > rec["longest_s"]["value"]):
            rec["longest_s"] = {"value": dur, **when}
    rec["rep_max"] = {str(k): v for k, v in sorted(rec["rep_max"].items())}
    return rec


_PR_LABELS = {"heaviest": "peso massimo", "best_e1rm": "massimale stimato", "best_set_volume": "miglior serie",
              "best_session_volume": "volume", "most_reps": "più ripetizioni", "longest_s": "durata"}


def session_prs(data: Data, session: dict, formula: str = "epley") -> list[dict]:
    """New records set in this session compared with everything before it."""
    out = []
    started = session.get("started_at") or ""
    for ex_id in dict.fromkeys(s["exercise_id"] for s in data.sets_by_session.get(session["id"], [])):
        before = exercise_records(data, ex_id, formula, before=started)
        upto = exercise_records(data, ex_id, formula, before=_after(started))
        name = (data.exercises.get(ex_id) or {}).get("name", "?")
        for key, label in _PR_LABELS.items():
            new, old = upto.get(key), before.get(key)
            if new and new.get("session_id") == session["id"] and (not old or new["value"] > old["value"]):
                out.append({"exercise_id": ex_id, "exercise": name, "kind": key, "label": label,
                            "value": new["value"], "previous": old["value"] if old else None,
                            "weight": new.get("weight"), "reps": new.get("reps"), "first": old is None})
    return out


def _after(iso: str) -> str:
    t = parse_dt(iso)
    return (t + timedelta(seconds=1)).isoformat() if t else "9999"


def recent_prs(data: Data, days: int = 30, formula: str = "epley", limit: int = 10) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    for sess in reversed(data.sessions):
        if (sess.get("started_at") or "") < since:
            break
        for pr in session_prs(data, sess, formula):
            if pr["first"]:
                continue        # the first time is a baseline, not a record
            out.append({**pr, "date": sess.get("started_at"), "session_id": sess["id"]})
            if len(out) >= limit:
                return out
    return out


# ── periods ──────────────────────────────────────────────────────────────────

def period_start(d: date, per: str, week_start: int = 0) -> date:
    if per == "day":
        return d
    if per == "month":
        return d.replace(day=1)
    return d - timedelta(days=(d.weekday() - week_start) % 7)


def period_next(start: date, per: str) -> date:
    if per == "day":
        return start + timedelta(days=1)
    if per == "month":
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start + timedelta(days=7)


def local_date(iso: Any, tz) -> date | None:
    t = parse_dt(iso)
    return t.astimezone(tz).date() if t else None


def muscle_sets(data: Data, sessions: Iterable[dict]) -> dict[str, float]:
    """Hard sets per muscle (primary 1, secondary 0.5)."""
    out: dict[str, float] = defaultdict(float)
    for sess in sessions:
        for st in data.sets_by_session.get(sess["id"], []):
            if not is_hard(st):
                continue
            ex = data.exercises.get(st["exercise_id"]) or {}
            for m in ex.get("primary_muscles") or []:
                out[m] += 1
            for m in ex.get("secondary_muscles") or []:
                out[m] += 0.5
    return dict(out)


def group_sets(muscles: dict[str, float]) -> dict[str, float]:
    out = {g: 0.0 for g in MUSCLE_GROUPS}
    for m, v in muscles.items():
        g = group_of(m)
        if g:
            out[g] += v
    return {g: round(v, 1) for g, v in out.items()}


def session_summary(data: Data, sess: dict) -> dict:
    sets = data.sets_by_session.get(sess["id"], [])
    work = [s for s in sets if is_working(s)]
    vol = sum((data.load(s) or 0) * (s.get("reps") or 0) for s in work)
    start, end = parse_dt(sess.get("started_at")), parse_dt(sess.get("ended_at"))
    return {"id": sess["id"], "name": sess.get("name"), "started_at": sess.get("started_at"),
            "ended_at": sess.get("ended_at"), "duration_min": round((end - start).total_seconds() / 60) if start and end else None,
            "sets": len(work), "volume": round(vol), "exercises": len({s["exercise_id"] for s in sets}),
            "template_id": sess.get("template_id"), "source": sess.get("source"),
            "perceived_effort": sess.get("perceived_effort")}


def periods(data: Data, per: str, count: int, tz, week_start: int = 0, today: date | None = None) -> list[dict]:
    """Last ``count`` periods (oldest first) with sessions, duration, volume, sets and hard sets per group."""
    today = today or datetime.now(tz).date()
    starts = [period_start(today, per, week_start)]
    for _ in range(count - 1):
        prev = period_start(starts[0] - timedelta(days=1), per, week_start)
        starts.insert(0, prev)
    buckets: dict[date, list[dict]] = {s: [] for s in starts}
    for sess in data.sessions:
        d = local_date(sess.get("started_at"), tz)
        if d is None or d < starts[0]:
            continue
        key = period_start(d, per, week_start)
        if key in buckets:
            buckets[key].append(sess)
    out = []
    for start in starts:
        sessions = buckets[start]
        sums = [session_summary(data, s) for s in sessions]
        out.append({"start": start.isoformat(), "end": period_next(start, per).isoformat(), "sessions": len(sessions),
                    "duration_min": sum(s["duration_min"] or 0 for s in sums), "volume": sum(s["volume"] for s in sums),
                    "sets": sum(s["sets"] for s in sums), "groups": group_sets(muscle_sets(data, sessions))})
    return out


def heatmap(data: Data, days: int, tz) -> list[dict]:
    since = datetime.now(tz).date() - timedelta(days=days)
    counts: dict[str, int] = defaultdict(int)
    for sess in data.sessions:
        d = local_date(sess.get("started_at"), tz)
        if d and d >= since:
            counts[d.isoformat()] += 1
    return [{"date": k, "count": v} for k, v in sorted(counts.items())]

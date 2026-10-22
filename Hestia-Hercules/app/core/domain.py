"""Shapes of Hercules data (SPEC §3) and their normalization.

Rows travel between the UI (offline outbox), the assistant tools and Archive with the same shapes, so
everything that writes goes through ``normalize(kind, data)``: unknown keys are kept (forward compatible),
known keys are coerced, ids default to new UUIDs.
"""
from __future__ import annotations

import uuid
from typing import Any

from .catalog import EQUIPMENT, KINDS, MUSCLES, PATTERNS, JOINTS

SET_TYPES = ("warmup", "normal", "drop", "failure")
PROGRESSIONS = ("double", "linear", "rpe", "none")
SESSION_STATUS = ("active", "done", "discarded")
PLAN_STATUS = ("planned", "skipped", "moved")
PERIODS = ("day", "week", "month")
MEASUREMENTS = {"bodyweight": "kg", "body_fat": "%", "waist": "cm", "chest": "cm", "arm": "cm", "thigh": "cm",
                "hips": "cm", "neck": "cm", "calf": "cm", "forearm": "cm", "shoulders": "cm"}
FEEDBACK_TAGS = ("too_heavy", "too_light", "pain", "great", "tired", "bored", "short_time", "technique")


class Invalid(ValueError):
    pass


def new_id() -> str:
    return str(uuid.uuid4())


def _num(v: Any, *, lo: float | None = None, hi: float | None = None, integer: bool = False) -> float | int | None:
    if v is None or v == "":
        return None
    try:
        x = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        raise Invalid(f"numero non valido: {v!r}")
    if lo is not None and x < lo:
        raise Invalid(f"{v} sotto il minimo {lo}")
    if hi is not None and x > hi:
        raise Invalid(f"{v} sopra il massimo {hi}")
    return int(round(x)) if integer else round(x, 3)


def _str(v: Any, limit: int = 2000) -> str:
    return str(v or "").strip()[:limit]


def _list(v: Any, allowed: dict | tuple | None = None) -> list:
    items = v if isinstance(v, list) else ([] if v in (None, "") else [v])
    out = [str(i).strip() for i in items if str(i).strip()]
    if allowed is not None:
        bad = [i for i in out if i not in allowed]
        if bad:
            raise Invalid(f"valori non validi: {bad}")
    return list(dict.fromkeys(out))


def exercise(d: dict) -> dict:
    name = _str(d.get("name"), 120)
    if not name:
        raise Invalid("l'esercizio ha bisogno di un nome")
    equip = d.get("equipment") or "other"
    kind = d.get("kind") or "weight_reps"
    pattern = d.get("movement_pattern") or "isolation"
    if equip not in EQUIPMENT or kind not in KINDS or pattern not in PATTERNS:
        raise Invalid("attrezzo, tipo o schema motorio non validi")
    return {**d, "name": name, "aliases": _list(d.get("aliases")),
            "primary_muscles": _list(d.get("primary_muscles"), MUSCLES),
            "secondary_muscles": _list(d.get("secondary_muscles"), MUSCLES),
            "stress_joints": _list(d.get("stress_joints"), JOINTS), "equipment": equip, "kind": kind,
            "movement_pattern": pattern, "unilateral": bool(d.get("unilateral")),
            "is_custom": bool(d.get("is_custom", True)), "archived": bool(d.get("archived")),
            "notes": _str(d.get("notes")), "instructions": _str(d.get("instructions"), 4000),
            "increment_kg": _num(d.get("increment_kg"), lo=0, hi=50), "media_url": _str(d.get("media_url"), 500),
            "favorite": bool(d.get("favorite"))}


def planned_set(d: dict) -> dict:
    t = d.get("type") or "normal"
    if t not in SET_TYPES:
        raise Invalid(f"tipo di serie non valido: {t}")
    rmin = _num(d.get("reps_min", d.get("reps")), lo=0, hi=200, integer=True)
    rmax = _num(d.get("reps_max", d.get("reps")), lo=0, hi=200, integer=True)
    if rmin is not None and rmax is not None and rmin > rmax:
        rmin, rmax = rmax, rmin
    return {"type": t, "reps_min": rmin, "reps_max": rmax, "weight_kg": _num(d.get("weight_kg"), lo=-500, hi=1000),
            "rpe": _num(d.get("rpe"), lo=1, hi=10), "duration_s": _num(d.get("duration_s"), lo=0, hi=36000, integer=True),
            "distance_m": _num(d.get("distance_m"), lo=0, hi=100000)}


def template_item(d: dict) -> dict:
    if not d.get("exercise_id"):
        raise Invalid("ogni voce della scheda ha bisogno di un esercizio")
    prog = d.get("progression") or "double"
    if prog not in PROGRESSIONS:
        raise Invalid(f"progressione non valida: {prog}")
    sets = [planned_set(s) for s in (d.get("sets") or [])] or [planned_set({"reps_min": 8, "reps_max": 12}) for _ in range(3)]
    return {"id": d.get("id") or new_id(), "exercise_id": str(d["exercise_id"]),
            "superset": _str(d.get("superset"), 10) or None,
            "rest_seconds": _num(d.get("rest_seconds"), lo=0, hi=1800, integer=True),
            "notes": _str(d.get("notes")), "progression": prog, "priority": _num(d.get("priority"), lo=1, hi=3, integer=True) or 2,
            "sets": sets}


def template(d: dict) -> dict:
    name = _str(d.get("name"), 120)
    if not name:
        raise Invalid("la scheda ha bisogno di un nome")
    return {**d, "name": name, "folder": _str(d.get("folder"), 80), "notes": _str(d.get("notes")),
            "color": _str(d.get("color"), 20), "position": _num(d.get("position"), integer=True) or 0,
            "archived": bool(d.get("archived")), "favorite": bool(d.get("favorite")),
            "items": [template_item(i) for i in (d.get("items") or [])],
            "revision": int(d.get("revision") or 0)}


def program(d: dict) -> dict:
    name = _str(d.get("name"), 120)
    if not name:
        raise Invalid("il programma ha bisogno di un nome")
    mode = d.get("mode") or "weekly"
    if mode not in ("weekly", "rotation"):
        raise Invalid("modo programma: weekly o rotation")
    days = []
    for day in d.get("days") or []:
        if not day.get("template_id"):
            continue
        wd = _num(day.get("weekday"), lo=0, hi=6, integer=True)
        days.append({"weekday": wd, "template_id": str(day["template_id"]), "label": _str(day.get("label"), 40)})
    return {**d, "name": name, "mode": mode, "active": bool(d.get("active", True)), "days": days,
            "start_date": _str(d.get("start_date"), 10), "deload_every_weeks": _num(d.get("deload_every_weeks"), lo=0, hi=52, integer=True),
            "notes": _str(d.get("notes"))}


def session_exercise(d: dict) -> dict:
    if not d.get("exercise_id"):
        raise Invalid("esercizio mancante")
    return {"id": d.get("id") or new_id(), "exercise_id": str(d["exercise_id"]),
            "superset": _str(d.get("superset"), 10) or None, "notes": _str(d.get("notes")),
            "rest_seconds": _num(d.get("rest_seconds"), lo=0, hi=1800, integer=True),
            "replaced_from": d.get("replaced_from") or None, "template_item_id": d.get("template_item_id") or None,
            "planned": [planned_set(s) for s in (d.get("planned") or [])], "skipped": bool(d.get("skipped"))}


def session(d: dict) -> dict:
    status = d.get("status") or "active"
    if status not in SESSION_STATUS:
        raise Invalid(f"stato non valido: {status}")
    if not d.get("started_at"):
        raise Invalid("started_at mancante")
    readiness = d.get("readiness") or {}
    return {**d, "name": _str(d.get("name"), 120) or "Allenamento", "status": status,
            "started_at": d["started_at"], "ended_at": d.get("ended_at") or None,
            "template_id": d.get("template_id") or None, "program_id": d.get("program_id") or None,
            "notes": _str(d.get("notes")), "source": d.get("source") or "live",
            "readiness": {k: readiness.get(k) for k in ("energy", "sleep", "soreness", "stress", "pain_areas",
                                                         "time_minutes", "free_text") if k in readiness},
            "perceived_effort": _num(d.get("perceived_effort"), lo=1, hi=10, integer=True),
            "bodyweight_kg": _num(d.get("bodyweight_kg"), lo=20, hi=400),
            "exercises": [session_exercise(e) for e in (d.get("exercises") or [])]}


def logged_set(d: dict) -> dict:
    t = d.get("type") or "normal"
    if t not in SET_TYPES:
        raise Invalid(f"tipo di serie non valido: {t}")
    for k in ("session_id", "session_exercise_id", "exercise_id"):
        if not d.get(k):
            raise Invalid(f"{k} mancante")
    return {**d, "session_id": str(d["session_id"]), "session_exercise_id": str(d["session_exercise_id"]),
            "exercise_id": str(d["exercise_id"]), "type": t,
            "position": _num(d.get("position"), lo=0, hi=200, integer=True) or 0,
            "weight_kg": _num(d.get("weight_kg"), lo=-500, hi=1000), "reps": _num(d.get("reps"), lo=0, hi=1000, integer=True),
            "rpe": _num(d.get("rpe"), lo=1, hi=10), "rir": _num(d.get("rir"), lo=0, hi=10),
            "duration_s": _num(d.get("duration_s"), lo=0, hi=36000, integer=True),
            "distance_m": _num(d.get("distance_m"), lo=0, hi=100000),
            "completed": bool(d.get("completed", True)), "completed_at": d.get("completed_at") or None,
            "notes": _str(d.get("notes"), 300)}


def measurement(d: dict) -> dict:
    kind = _str(d.get("kind"), 40) or "bodyweight"
    value = _num(d.get("value"), lo=0, hi=1000)
    if value is None:
        raise Invalid("valore mancante")
    if not d.get("taken_at"):
        raise Invalid("taken_at mancante")
    return {**d, "kind": kind, "value": value, "unit": _str(d.get("unit"), 10) or MEASUREMENTS.get(kind, ""),
            "taken_at": d["taken_at"], "notes": _str(d.get("notes"), 300)}


def feedback(d: dict) -> dict:
    tags = _list(d.get("tags"), FEEDBACK_TAGS)
    text = _str(d.get("text"), 1000)
    if not tags and not text:
        raise Invalid("feedback vuoto")
    return {**d, "tags": tags, "text": text, "session_id": d.get("session_id") or None,
            "exercise_id": d.get("exercise_id") or None, "at": d.get("at"),
            "joints": _list(d.get("joints"), JOINTS), "source": d.get("source") or "ui"}


def goal(d: dict) -> dict:
    scope = d.get("scope") or "any"
    if scope not in ("any", "template", "muscle"):
        raise Invalid("ambito obiettivo: any, template o muscle")
    per = d.get("per") or "week"
    if per not in PERIODS:
        raise Invalid("periodo: day, week o month")
    times = _num(d.get("times"), lo=1, hi=31, integer=True)
    if not times:
        raise Invalid("quante volte?")
    if scope != "any" and not d.get("target_id"):
        raise Invalid("obiettivo specifico senza scheda o muscolo")
    return {**d, "scope": scope, "target_id": d.get("target_id") or None, "times": times, "per": per,
            "active": bool(d.get("active", True)), "min_hard_sets": _num(d.get("min_hard_sets"), lo=1, hi=30, integer=True) or 4,
            "label": _str(d.get("label"), 80)}


def plan(d: dict) -> dict:
    """A day override of the program: do template X on date D, or skip D, or D moved elsewhere."""
    day = _str(d.get("date"), 10)
    if len(day) != 10:
        raise Invalid("data mancante (YYYY-MM-DD)")
    status = d.get("status") or "planned"
    if status not in PLAN_STATUS:
        raise Invalid(f"stato non valido: {status}")
    return {**d, "date": day, "status": status, "template_id": d.get("template_id") or None,
            "from_date": _str(d.get("from_date"), 10) or None, "note": _str(d.get("note"), 300)}


def checkin(d: dict) -> dict:
    """How I feel today (energy 1–5, sleep 1–5, soreness/pain areas, minutes available)."""
    if not d.get("at"):
        raise Invalid("at mancante")
    return {**d, "energy": _num(d.get("energy"), lo=1, hi=5, integer=True),
            "sleep": _num(d.get("sleep"), lo=1, hi=5, integer=True), "stress": _num(d.get("stress"), lo=1, hi=5, integer=True),
            "soreness": _list(d.get("soreness")), "pain_areas": _list(d.get("pain_areas")),
            "time_minutes": _num(d.get("time_minutes"), lo=5, hi=300, integer=True),
            "equipment_missing": _list(d.get("equipment_missing"), EQUIPMENT), "free_text": _str(d.get("free_text"), 1000)}


NORMALIZERS = {"plan": plan, "checkin": checkin, "exercise": exercise, "template": template, "program": program, "session": session, "set": logged_set,
               "measurement": measurement, "feedback": feedback, "goal": goal, "adaptation": lambda d: dict(d), "reminder": lambda d: dict(d),
               "activity_plan": lambda d: _activities().norm_plan(d), "activity": lambda d: _activities().norm_activity(d)}


def _activities():
    from . import activities                       # outdoor activities live in their own module (imports domain)
    return activities


def normalize(kind: str, data: dict) -> dict:
    fn = NORMALIZERS.get(kind)
    if fn is None:
        raise Invalid(f"tipo sconosciuto: {kind}")
    return fn(dict(data or {}))


def index_columns(kind: str, data: dict) -> dict:
    """Store columns (parent/ref/at) derived from the data, so queries by time/exercise/session work."""
    if kind == "session":
        return {"ref_id": data.get("template_id"), "at": data.get("started_at")}
    if kind == "set":
        return {"parent_id": data.get("session_id"), "ref_id": data.get("exercise_id"), "at": data.get("session_at")}
    if kind == "measurement":
        return {"ref_id": data.get("kind"), "at": data.get("taken_at")}
    if kind == "feedback":
        return {"parent_id": data.get("session_id"), "ref_id": data.get("exercise_id"), "at": data.get("at")}
    if kind == "plan":
        return {"ref_id": data.get("template_id"), "at": (data.get("date") or "") + "T12:00:00+00:00"}
    if kind == "checkin":
        return {"at": data.get("at")}
    if kind == "activity_plan":
        return {"ref_id": data.get("kind"), "at": (data.get("week_from") or "") + "T12:00:00+00:00"}
    if kind == "activity":
        return {"ref_id": data.get("kind"), "at": data.get("at") or (data.get("date") or "") + "T12:00:00+00:00"}
    if kind == "adaptation":
        return {"parent_id": data.get("session_id"), "at": data.get("created_at")}
    return {}

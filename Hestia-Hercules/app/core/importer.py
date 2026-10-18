"""Import from Strong / Hevy CSV exports and export everything (SPEC §4.7).

Import is two steps: ``preview`` parses the file and maps exercise names to the catalog (unknown names are
listed for review), ``build`` turns it into sessions + sets with the mapping I confirmed (or new custom
exercises). Ids are deterministic per file row, so importing the same file twice changes nothing.
"""
from __future__ import annotations

import csv
import io
import re
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from .catalog import NAMESPACE

_EQUIP_WORDS = {"barbell": "barbell", "dumbbell": "dumbbell", "machine": "machine", "cable": "cable",
                "bodyweight": "bodyweight", "smith machine": "smith", "ez bar": "ez_bar", "kettlebell": "kettlebell",
                "band": "band", "trap bar": "trap_bar", "weighted": "bodyweight", "assisted": "machine"}
_LB = 0.45359237


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9àèéìòù ]+", " ", (s or "").lower()).strip()


def _split(name: str) -> tuple[str, str | None]:
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", name or "")
    if not m:
        return _norm(name), None
    return _norm(m.group(1)), _EQUIP_WORDS.get(m.group(2).strip().lower())


def match_exercise(name: str, exercises: list[dict]) -> dict | None:
    full = _norm(name)
    base, equip = _split(name)
    best = None
    for ex in exercises:
        names = {_norm(ex.get("name", ""))} | {_norm(a) for a in ex.get("aliases") or []}
        if full in names:
            return ex
        if base in names and (equip is None or ex.get("equipment") == equip):
            if best is None or (equip and ex.get("equipment") == equip):
                best = ex
    return best


def detect(text: str) -> str:
    head = text.lstrip("﻿").split("\n", 1)[0].lower()
    if "exercise_title" in head:
        return "hevy"
    if "exercise name" in head and "set order" in head:
        return "strong"
    raise ValueError("formato non riconosciuto: serve un export CSV di Strong o Hevy")


def _parse_dt(s: str, tz) -> datetime | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d %b %Y, %H:%M", "%d %b %Y %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=tz)
    except ValueError:
        return None


def _f(v) -> float | None:
    try:
        return float(str(v).replace(",", ".")) if str(v).strip() not in ("", "None") else None
    except ValueError:
        return None


def _duration(s: str) -> timedelta:
    """Strong's 'Duration' like '1h 5m' or '45m' or seconds."""
    s = (s or "").strip()
    if not s:
        return timedelta(minutes=60)
    if s.isdigit():
        return timedelta(seconds=int(s))
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*m", s)
    return timedelta(hours=int(h.group(1)) if h else 0, minutes=int(m.group(1)) if m else 0) or timedelta(minutes=60)


def parse(text: str, tz, unit: str = "kg") -> dict:
    """→ {format, workouts: [{key, name, started_at, ended_at, notes, exercises: OrderedDict name → sets}]}"""
    text = text.lstrip("﻿")
    fmt = detect(text)
    delim = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
    workouts: "OrderedDict[str, dict]" = OrderedDict()
    for r in rows:
        if fmt == "strong":
            start = _parse_dt(r.get("Date", ""), tz)
            if not start:
                continue
            key = f"strong|{r.get('Date')}|{r.get('Workout Name')}"
            w = workouts.setdefault(key, {"key": key, "name": r.get("Workout Name") or "Allenamento",
                                          "started_at": start, "ended_at": start + _duration(r.get("Duration", "")),
                                          "notes": r.get("Workout Notes") or "", "exercises": OrderedDict()})
            order = str(r.get("Set Order") or "")
            weight = _f(r.get("Weight"))
            if weight is not None and unit == "lb":
                weight = round(weight * _LB, 2)
            st = {"type": "warmup" if order.upper() == "W" else ("drop" if order.upper() == "D" else
                                                                 "failure" if order.upper() == "F" else "normal"),
                  "weight_kg": weight, "reps": int(_f(r.get("Reps")) or 0) or None, "rpe": _f(r.get("RPE")),
                  "duration_s": int(_f(r.get("Seconds")) or 0) or None, "distance_m": _f(r.get("Distance")) or None,
                  "notes": r.get("Notes") or ""}
            name = r.get("Exercise Name") or "?"
        else:
            start = _parse_dt(r.get("start_time", ""), tz)
            if not start:
                continue
            key = f"hevy|{r.get('start_time')}|{r.get('title')}"
            end = _parse_dt(r.get("end_time", ""), tz) or start + timedelta(hours=1)
            w = workouts.setdefault(key, {"key": key, "name": r.get("title") or "Allenamento", "started_at": start,
                                          "ended_at": end, "notes": r.get("description") or "",
                                          "exercises": OrderedDict()})
            km = _f(r.get("distance_km"))
            st = {"type": {"warmup": "warmup", "dropset": "drop", "failure": "failure"}.get(
                      (r.get("set_type") or "normal").lower(), "normal"),
                  "weight_kg": _f(r.get("weight_kg")), "reps": int(_f(r.get("reps")) or 0) or None,
                  "rpe": _f(r.get("rpe")), "duration_s": int(_f(r.get("duration_seconds")) or 0) or None,
                  "distance_m": km * 1000 if km else None, "notes": ""}
            name = r.get("exercise_title") or "?"
        w["exercises"].setdefault(name, []).append(st)
    return {"format": fmt, "workouts": list(workouts.values())}


def preview(text: str, exercises: list[dict], tz, unit: str = "kg") -> dict:
    parsed = parse(text, tz, unit)
    names: dict[str, int] = {}
    for w in parsed["workouts"]:
        for n, sets in w["exercises"].items():
            names[n] = names.get(n, 0) + len(sets)
    mapping = []
    for n, count in sorted(names.items(), key=lambda x: -x[1]):
        ex = match_exercise(n, exercises)
        mapping.append({"name": n, "sets": count, "exercise_id": ex["id"] if ex else None,
                        "exercise": ex["name"] if ex else None})
    ws = parsed["workouts"]
    return {"format": parsed["format"], "workouts": len(ws), "sets": sum(names.values()),
            "from": min((w["started_at"] for w in ws), default=None), "to": max((w["started_at"] for w in ws), default=None),
            "mapping": mapping, "unknown": [m["name"] for m in mapping if not m["exercise_id"]]}


def _rid(*parts) -> str:
    return str(uuid.uuid5(NAMESPACE, "import|" + "|".join(str(p) for p in parts)))


def build(text: str, mapping: dict[str, str], exercises: list[dict], tz, unit: str = "kg") -> dict:
    """→ {exercises: new custom ones, sessions, sets} ready for the store. ``mapping`` name → exercise id or 'new'."""
    parsed = parse(text, tz, unit)
    new_ex: dict[str, dict] = {}
    resolved: dict[str, str] = {}
    for name in {n for w in parsed["workouts"] for n in w["exercises"]}:
        target = mapping.get(name)
        if not target:
            ex = match_exercise(name, exercises)
            target = ex["id"] if ex else "new"
        if target == "new":
            eid = _rid("exercise", _norm(name))
            base, equip = _split(name)
            new_ex[eid] = {"id": eid, "name": name, "aliases": [], "primary_muscles": [], "secondary_muscles": [],
                           "equipment": equip or "other", "kind": "weight_reps", "movement_pattern": "isolation",
                           "stress_joints": [], "is_custom": True, "notes": f"Importato da {parsed['format']}"}
            target = eid
        resolved[name] = target
    sessions, sets = [], []
    for w in parsed["workouts"]:
        sid = _rid(w["key"])
        sess_ex = []
        for i, (name, wsets) in enumerate(w["exercises"].items()):
            seid = _rid(w["key"], name)
            sess_ex.append({"id": seid, "exercise_id": resolved[name]})
            for pos, st in enumerate(wsets):
                sets.append({**st, "id": _rid(w["key"], name, pos), "session_id": sid, "session_exercise_id": seid,
                             "exercise_id": resolved[name], "position": pos, "completed": True,
                             "session_at": w["started_at"].isoformat()})
        sessions.append({"id": sid, "name": w["name"], "status": "done", "started_at": w["started_at"].isoformat(),
                         "ended_at": w["ended_at"].isoformat(), "notes": w["notes"], "source": parsed["format"],
                         "exercises": sess_ex})
    return {"exercises": list(new_ex.values()), "sessions": sessions, "sets": sets}


def export_csv(sessions: list[dict], sets: list[dict], exercises: dict[str, dict]) -> str:
    by_session = {s["id"]: s for s in sessions}
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["date", "workout", "exercise", "set", "type", "weight_kg", "reps", "rpe", "duration_s",
                "distance_m", "notes", "session_notes"])
    for st in sorted(sets, key=lambda s: (s.get("session_at") or "", s.get("session_exercise_id") or "",
                                          s.get("position") or 0)):
        sess = by_session.get(st.get("session_id"))
        if not sess or sess.get("status") != "done":
            continue
        w.writerow([sess.get("started_at"), sess.get("name"), (exercises.get(st["exercise_id"]) or {}).get("name"),
                    (st.get("position") or 0) + 1, st.get("type"), st.get("weight_kg"), st.get("reps"), st.get("rpe"),
                    st.get("duration_s"), st.get("distance_m"), st.get("notes"), sess.get("notes")])
    return out.getvalue()

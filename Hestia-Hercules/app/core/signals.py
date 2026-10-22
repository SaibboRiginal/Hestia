"""Reflection signals (docs/work/2026-10-20-riflessione-a-livelli): short deterministic facts about the user's
training + weekly series, published to Archive through ``hestia_common.signals_client``.

Nothing new is judged here: stall, low energy, missed days, PRs and goals come from the engines the summary already
uses; this file only picks what is worth a signal and words it (Italian, «Allenamento», never the module name).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING

from hestia_common.signals_client import iso_week, last_weeks, metric, signal

from . import progression, records
from .records import local_date

if TYPE_CHECKING:
    from .service import Hercules

WEEKS = 12              # weekly series length (current week included)
STALL_RECENT_DAYS = 30  # a stall on an exercise not trained for a month is history, not a signal
LOW_ENERGY = 2          # same threshold as summary(): energy ≤ 2 on the 1–5 scale
DELOAD_CHECKINS = 3     # low check-ins in 7 days before suggesting a deload
PR_DAYS = 3
WEEKDAYS_SHORT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _name(data: records.Data, ex_id: str) -> str:
    return (data.exercises.get(ex_id) or {}).get("name") or "Esercizio"


def _stalls(h: "Hercules", data: records.Data, today: date) -> list[dict]:
    n = int(h.cfg("stall.exposures", 3))
    since = (today - timedelta(days=STALL_RECENT_DAYS)).isoformat()
    out = []
    for ex_id, sets in data.sets_by_exercise.items():
        if not sets or (sets[-1].get("session_at") or "")[:10] < since:
            continue
        s = progression.stall(data, ex_id, n, h.formula())
        if s:
            out.append({**s, "exercise": _name(data, ex_id)})
    return out


def low_checkins(h: "Hercules", today: date) -> list[dict]:
    since = today - timedelta(days=7)
    rows = [c for c in h.store.items("checkin") if (c.get("energy") or 5) <= LOW_ENERGY
            and (local_date(c.get("at"), h.tz) or date.min) > since]
    return sorted(rows, key=lambda c: c.get("at") or "")


def missed_streak(h: "Hercules", today: date, lookback: int = 28) -> list[date]:
    """Planned program days missed in a row, most recent first (before today). A done day ends the streak; a day
    the user skipped or moved is his decision: it neither counts nor breaks it."""
    prog = h.active_program()
    if not prog or prog.get("mode") != "weekly":
        return []
    weekdays = {x.get("weekday") for x in prog.get("days") or []}
    data = h.data()
    done = {local_date(s.get("started_at"), h.tz) for s in data.sessions}
    plans = {p["date"]: p for p in h.store.items("plan")}
    out = []
    for i in range(1, lookback + 1):
        d = today - timedelta(days=i)
        if d in done:
            break
        if d.weekday() not in weekdays or (plans.get(d.isoformat()) or {}).get("status") in ("skipped", "moved"):
            continue
        out.append(d)
    return out


def _fmt_day(d: date) -> str:
    return f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}"


def evaluate(h: "Hercules", today: date | None = None) -> tuple[list[dict], list[dict]]:
    """The current set of signals and the weekly metrics (last ``WEEKS`` ISO weeks)."""
    h.store.refresh()
    today = today or h.today()
    data = h.data()
    out: list[dict] = []
    for s in _stalls(h, data, today):
        what = "massimale stimato" if s["metric"] == "best_e1rm" else "ripetizioni"
        best = progression.fmt_kg(s["best"]) + (" kg" if s["metric"] == "best_e1rm" else "")
        out.append(signal(f"stall:{s['exercise_id']}", f"{s['exercise']} fermo da {s['exposures']} sedute: "
                          f"{what} non supera {best}", kind="trend", severity="attenzione",
                          metrics={"exposures": s["exposures"], "best": s["best"], "recent": s["recent"]},
                          page=f"esercizi/{s['exercise_id']}"))
    low = low_checkins(h, today)
    if len(low) >= DELOAD_CHECKINS:
        out.append(signal("deload", f"Energia bassa {len(low)} volte in 7 giorni: valuta settimana di scarico",
                          kind="trend", severity="attenzione", metrics={"low_checkins": len(low)}, page="allenamento"))
    missed = missed_streak(h, today)
    if len(missed) >= 2:
        out.append(signal("missed_streak", f"{len(missed)} allenamenti in programma saltati di fila "
                          f"(ultimo {_fmt_day(missed[0])})", kind="streak",
                          severity="alta" if len(missed) >= 4 else "attenzione", metrics={"missed": len(missed)},
                          page="allenamento"))
    seen = set()
    for pr in records.recent_prs(data, PR_DAYS, h.formula(), limit=20):
        if pr["exercise_id"] in seen:
            continue
        seen.add(pr["exercise_id"])
        out.append(signal(f"pr:{pr['exercise_id']}", f"Nuovo record {pr['exercise']}: {pr['label']} "
                          f"{progression.fmt_kg(pr['value'])}", kind="milestone", severity="info", ttl_days=PR_DAYS,
                          metrics={"value": pr["value"], "previous": pr.get("previous") or 0},
                          period=(local_date(pr.get("date"), h.tz) or today).isoformat(),
                          page=f"esercizi/{pr['exercise_id']}"))
    for g in h.goals():
        p = g["progress"]
        if p["per"] == "week" and p["behind"] and p["days_left"] <= 2:
            out.append(signal("week_goal", f"Obiettivo settimana indietro: {p['done']}/{p['times']}, "
                              f"{'resta' if p['days_left'] == 1 else 'restano'} {p['days_left']} "
                              f"{'giorno' if p['days_left'] == 1 else 'giorni'}", kind="goal", severity="attenzione",
                              metrics={"done": p["done"], "times": p["times"], "days_left": p["days_left"]},
                              period=iso_week(today), page="progressi"))
            break
    return out, weekly_metrics(h, data, today)


def weekly_metrics(h: "Hercules", data: records.Data, today: date) -> list[dict]:
    """Sessions, volume and average check-in energy per ISO week. Weeks before the first recorded workout are left
    out (no data yet is not «zero workouts»); energy only for weeks with check-ins."""
    weeks = last_weeks(WEEKS, today)
    if not data.sessions:
        return []
    first = iso_week(local_date(data.sessions[0].get("started_at"), h.tz) or today)
    sessions: dict[str, int] = defaultdict(int)
    volume: dict[str, float] = defaultdict(float)
    for s in data.sessions:
        d = local_date(s.get("started_at"), h.tz)
        if not d:
            continue
        w = iso_week(d)
        sessions[w] += 1
        volume[w] += records.session_summary(data, s)["volume"]
    energy: dict[str, list[float]] = defaultdict(list)
    for c in h.store.items("checkin"):
        d = local_date(c.get("at"), h.tz)
        if d and c.get("energy") is not None:
            energy[iso_week(d)].append(float(c["energy"]))
    out = []
    for w in weeks:
        if w < first:
            continue
        out.append(metric("fitness.sessions", w, sessions.get(w, 0), "Allenamenti"))
        out.append(metric("fitness.volume", w, round(volume.get(w, 0.0)), "Volume (kg)"))
        if energy.get(w):
            out.append(metric("fitness.energy", w, round(sum(energy[w]) / len(energy[w]), 2), "Energia media"))
    return out


def detail(h: "Hercules", topic: str, today: date | None = None) -> str | None:
    """A few facts behind one signal key (``/api/module/context?topic=``); ``None`` when the topic is unknown."""
    h.store.refresh()
    today = today or h.today()
    data = h.data()
    kind, _, ref = (topic or "").partition(":")
    if kind == "stall" and ref in data.exercises:
        hist = records.exposures(data, ref, h.formula())[-4:]
        bits = []
        for e in reversed(hist):
            d = local_date(e["date"], h.tz)
            top = f"{progression.fmt_kg(e['top_weight'])}×{e['top_reps']}" if e["top_weight"] is not None \
                else f"{e['max_reps']} rip"
            e1 = f" e1RM {progression.fmt_kg(e['best_e1rm'])}" if e["best_e1rm"] else ""
            bits.append(f"{d.strftime('%d/%m') if d else '?'} {top}{e1}")
        return f"Allenamento · {_name(data, ref)}, ultime sedute: " + "; ".join(bits) if bits else None
    if kind == "pr" and ref in data.exercises:
        prs = [p for p in records.recent_prs(data, 14, h.formula(), limit=50) if p["exercise_id"] == ref]
        if not prs:
            return None
        return f"Allenamento · {_name(data, ref)}, record recenti: " + "; ".join(
            f"{p['label']} {progression.fmt_kg(p['value'])} (prima {progression.fmt_kg(p.get('previous'))})" for p in prs)
    if topic == "missed_streak":
        missed = missed_streak(h, today)
        if not missed:
            return None
        return f"Allenamento · giorni in programma saltati di fila: {', '.join(_fmt_day(d) for d in missed)}"
    if topic == "deload":
        low = low_checkins(h, today)
        if not low:
            return None
        return "Allenamento · check-in energia bassa: " + "; ".join(
            f"{(local_date(c.get('at'), h.tz) or today).strftime('%d/%m')} energia {c.get('energy')}"
            + (f", sonno {c['sleep']}" if c.get("sleep") else "") for c in low)
    if topic == "week_goal":
        goals = [g["progress"] for g in h.goals() if g["progress"]["per"] == "week"]
        if not goals:
            return None
        week = records.periods(data, "week", 1, h.tz, h.week_start(), today)[-1]
        return "Allenamento · " + "; ".join(f"{g['label']}: {g['hint']}, mancano {g['remaining']}, "
                                             f"{g['days_left']} giorni alla fine" for g in goals) \
            + f" · settimana: {week['sessions']} allenamenti, {week['volume']} kg"
    return None

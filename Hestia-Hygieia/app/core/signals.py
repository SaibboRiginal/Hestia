"""Reflection signals (docs/work/2026-10-20-riflessione-a-livelli): short deterministic facts about the user's self
care + weekly series, published to Archive through ``hestia_common.signals_client``.

Built on what the planner and the statistics already judge (cadence goals, ``goal_state``, ``routine_stats`` streaks,
the journal scores). Expiry / restock alerts are reminders, not facts about the user: they stay out. Texts speak of
«Cura di sé», never of the module.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import TYPE_CHECKING

from hestia_common.signals_client import iso_week, last_weeks, metric, signal, week_start

from .planner import DONE_STATUSES, norm_cadence

if TYPE_CHECKING:
    from .service import Hygieia

WEEKS = 12              # weekly series length (current week included)
DROP_POINTS = 20        # adherence drop (this week vs mean of the previous 4) that makes a signal
STREAK_MILESTONES = (4, 8, 12, 26, 52)


def _first_day(h: "Hygieia", r: dict) -> date | None:
    """When a routine started to count: its first version, or an older logged day (imported / back-filled)."""
    days = [v.get("valid_from") for v in h.versions(r["id"]) if v.get("valid_from")]
    days += [l["date"] for l in h.items("log") if l.get("routine_id") == r["id"] and l.get("date")]
    return date.fromisoformat(min(days)) if days else None


def _need(cadence: dict, start: date, end: date) -> float:
    """How many times a cadence asks for in the days [start, end) (the open part of a week is prorated)."""
    days = (end - start).days
    if days <= 0:
        return 0.0
    c = norm_cadence(cadence)
    if c["mode"] == "daily":
        return float(days)
    if c["mode"] == "fixed_days":
        return float(sum(1 for k in range(days) if (start + timedelta(days=k)).weekday() in c["days"]))
    if c["mode"] == "target":
        span = 7 if c["per"] == "week" else calendar.monthrange(start.year, start.month)[1]
        return c["times"] * days / span
    return 0.0          # as needed: no goal


def week_adherence(h: "Hygieia", week: str, today: date) -> dict:
    """Per-routine done/need in an ISO week (until today), plus the overall % (done capped at need)."""
    start = week_start(week)
    end = min(start + timedelta(days=7), today + timedelta(days=1))
    logs = [l for l in h.items("log") if l.get("routine_id") and l.get("status") in DONE_STATUSES]
    rows = []
    for r in h.items("routine"):
        if r.get("status") != "active":
            continue
        first = _first_day(h, r)
        if not first or first >= end:
            continue
        need = _need(r.get("cadence"), max(start, first), end)
        if need <= 0:
            continue
        done = sum(1 for l in logs if l["routine_id"] == r["id"] and start.isoformat() <= l["date"] < end.isoformat())
        skipped = sum(1 for l in h.items("log") if l.get("routine_id") == r["id"] and l.get("status") == "skipped"
                      and start.isoformat() <= l.get("date", "") < end.isoformat())
        rows.append({"routine_id": r["id"], "name": r.get("name"), "done": done, "need": round(need, 2),
                     "skipped": skipped})
    need = sum(x["need"] for x in rows)
    got = sum(min(x["done"], x["need"]) for x in rows)
    return {"week": week, "routines": rows, "percent": round(100 * got / need) if need else None}


def evaluate(h: "Hygieia", today: date | None = None) -> tuple[list[dict], list[dict]]:
    """The current set of signals and the weekly metrics (last ``WEEKS`` ISO weeks)."""
    h.store.refresh()
    today = today or h.today()
    weeks = last_weeks(WEEKS, today)
    adherence = {w: week_adherence(h, w, today) for w in weeks}
    out: list[dict] = []
    now = adherence[weeks[-1]]["percent"]
    before = [adherence[w]["percent"] for w in weeks[-5:-1] if adherence[w]["percent"] is not None]
    if now is not None and before:
        mean = round(sum(before) / len(before))
        if mean - now >= DROP_POINTS:
            out.append(signal("adherence_drop", f"Routine rispettate {now}% questa settimana, prima {mean}%",
                              kind="trend", severity="attenzione", metrics={"percent": now, "previous": mean},
                              period=weeks[-1], page="statistiche"))
    for p in h.plan(today.isoformat())["routines"]:
        g = p["goal"]
        if g.get("mode") == "target" and g.get("behind") and p["state"] == "due":
            out.append(signal(f"goal:{p['routine_id']}", f"{p['name']} indietro: {g['hint']}, "
                              f"{g['days_left']} {'giorno' if g['days_left'] == 1 else 'giorni'} alla fine",
                              kind="goal", severity="attenzione",
                              metrics={"done": g["done"], "times": g["times"], "days_left": g["days_left"]},
                              page=f"routine/{p['routine_id']}"))
    for r in h.items("routine"):
        if r.get("status") != "active":
            continue
        st = h.routine_stats(r)
        if st["streak"] in STREAK_MILESTONES:
            unit = {"week": "settimane", "month": "mesi", "day": "giorni"}.get(st["per"], "periodi")
            out.append(signal(f"streak:{r['id']}", f"{r.get('name')}: obiettivo rispettato {st['streak']} {unit} di fila",
                              kind="milestone", severity="info", metrics={"streak": st["streak"]},
                              page=f"routine/{r['id']}"))
    told = _told(h, today)
    if told:
        # B9 spoken evening diary: the day told by the owner, read by the evening reflection (full text via topic)
        note = " ".join(str(told.get("note") or "").split())
        out.append(signal("diario", f"Giornata raccontata: {note[:200]}" + ("…" if len(note) > 200 else ""),
                          kind="trend", severity="info", metrics={"chars": len(note)}, period=today.isoformat(),
                          ttl_days=2, page="diario"))
    return out, weekly_metrics(h, weeks, adherence)


def _told(h: "Hygieia", day: date) -> dict | None:
    from .service import DIARY_AREA
    rows = [j for j in h.items("journal") if j.get("date") == day.isoformat() and j.get("area") == DIARY_AREA]
    return rows[-1] if rows else None


def weekly_metrics(h: "Hygieia", weeks: list[str], adherence: dict[str, dict]) -> list[dict]:
    """Adherence % (weeks with a goal to meet) and journal score averages per area/metric (weeks with entries)."""
    out = [metric("selfcare.adherence", w, adherence[w]["percent"], "Routine rispettate %")
           for w in weeks if adherence[w]["percent"] is not None]
    areas = {a["value"]: a["label"] for a in h.options("areas")}
    labels = {(area, m["value"]): m["label"] for area, ms in h.options("metrics").items() for m in ms}
    scores: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    first = weeks[0]
    for j in h.items("journal"):
        if not j.get("date"):
            continue
        w = iso_week(date.fromisoformat(j["date"]))
        if w < first:
            continue
        for k, v in (j.get("scores") or {}).items():
            scores[(j.get("area") or "", k)][w].append(float(v))
    for (area, k), by_week in sorted(scores.items()):
        label = labels.get((area, k)) or labels.get(("*", k)) or k.replace("_", " ").capitalize()
        for w, vals in sorted(by_week.items()):
            out.append(metric(f"selfcare.journal.{area}.{k}", w, round(sum(vals) / len(vals), 2),
                              f"Diario {areas.get(area, area)} · {label}"))
    return out


def detail(h: "Hygieia", topic: str, today: date | None = None) -> str | None:
    """A few facts behind one signal key (``/api/module/context?topic=``); ``None`` when the topic is unknown."""
    h.store.refresh()
    today = today or h.today()
    kind, _, ref = (topic or "").partition(":")
    if topic == "diario":
        told = _told(h, today)
        return f"Diario della giornata ({today.isoformat()}): {told.get('note')}" if told else None
    if topic == "adherence_drop":
        weeks = last_weeks(5, today)
        cur = week_adherence(h, weeks[-1], today)
        prev = [week_adherence(h, w, today) for w in weeks[:-1]]
        bits = []
        for x in cur["routines"]:
            before = [r for p in prev for r in p["routines"] if r["routine_id"] == x["routine_id"]]
            b = f", prima {sum(r['done'] for r in before)}/{round(sum(r['need'] for r in before))} in 4 sett." if before else ""
            bits.append(f"{x['name']} {x['done']}/{round(x['need'], 1):g}" + (f" saltata {x['skipped']}" if x["skipped"] else "") + b)
        missed = [x for x in cur["routines"] if x["done"] < x["need"]]
        head = f"Cura di sé · settimana {cur['percent']}%"
        if missed:
            head += ", indietro: " + ", ".join(x["name"] for x in missed)
        return head + (" · " + "; ".join(bits) if bits else "")
    if kind in ("goal", "streak") and ref:
        r = h.store.data("routine", ref)
        if not r:
            return None
        p = h.day(today).plan_routine({**r, "id": ref})
        st = h.routine_stats({**r, "id": ref})
        g = p["goal"]
        hist = "; ".join(f"{x['start']} {x['done']}/{x['need']}" for x in st["history"][-4:])
        return (f"Cura di sé · {r.get('name')}: {g.get('hint', '')}, ultima {g.get('last_done') or 'mai'}, "
                f"serie {st['streak']}, rispettata {st['adherence'] if st['adherence'] is not None else '?'}% · {hist}")
    return None

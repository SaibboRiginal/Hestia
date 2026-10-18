"""Next-time suggestions and stall detection (SPEC §5.1) — deterministic, explained.

``suggest`` returns, for each planned set of a template item, the weight and reps to aim for, plus a short
Italian reason the UI and the assistant show as is ("tutte le serie a 12: +2,5 kg").
"""
from __future__ import annotations

import math
from typing import Any

from .records import Data, e1rm, exposures, is_working

DEFAULT_INCREMENTS = {"barbell": 2.5, "dumbbell": 2.0, "machine": 5.0, "cable": 2.5, "smith": 2.5,
                      "ez_bar": 2.5, "trap_bar": 2.5, "kettlebell": 4.0, "band": 0.0, "bodyweight": 2.5, "other": 2.5}


def increment_for(exercise: dict, increments: dict | None = None) -> float:
    if exercise.get("increment_kg"):
        return float(exercise["increment_kg"])
    inc = (increments or {}).get(exercise.get("equipment") or "other")
    return float(inc if inc is not None else DEFAULT_INCREMENTS.get(exercise.get("equipment") or "other", 2.5))


def round_to(weight: float | None, inc: float) -> float | None:
    if weight is None:
        return None
    if not inc:
        return round(weight, 1)
    return round(math.floor(weight / inc + 0.5) * inc, 2)


def fmt_kg(x: float | None) -> str:
    if x is None:
        return "—"
    return (f"{x:.2f}".rstrip("0").rstrip(".")).replace(".", ",")


def _rpe_weight(e1: float, reps: int, rpe: float) -> float:
    """Epley inverted with reps in reserve: target reps + (10 - RPE) = reps the weight allows."""
    total = reps + max(0.0, 10 - rpe)
    return e1 / (1 + total / 30) if total > 1 else e1


def suggest(data: Data, item: dict, exercise: dict, *, formula: str = "epley", increments: dict | None = None,
            feedback: list[dict] | None = None) -> dict:
    """Targets for one template item from its last exposure. Bodyweight kinds suggest reps (and extra load)."""
    planned = item.get("sets") or []
    work_plan = [p for p in planned if p.get("type", "normal") != "warmup"]
    history = exposures(data, exercise["id"], formula)
    inc = increment_for(exercise, increments)
    rule = item.get("progression") or "double"
    last = history[-1] if history else None
    targets = [{**p, "weight_kg": p.get("weight_kg"), "reps": p.get("reps_max") or p.get("reps_min")} for p in planned]
    out = {"exercise_id": exercise["id"], "rule": rule, "increment": inc, "last": None, "sets": targets,
           "reason": "Nessuno storico: usa i valori della scheda.", "action": "plan"}
    if not last:
        return out
    last_work = [s for s in last["detail"] if s.get("type") in ("normal", "drop", "failure", None)]
    out["last"] = {"date": last["date"], "sets": last["detail"], "top_weight": last["top_weight"],
                   "top_reps": last["top_reps"], "best_e1rm": last["best_e1rm"]}
    last_w = last["top_weight"] if last["top_weight"] is not None else (last_work[0].get("weight_kg") if last_work else None)
    blocked = _feedback_blocks(feedback or [], exercise["id"], last["date"])

    def apply(weight, reps_for, reason, action):
        sets = []
        wi = 0
        for p in planned:
            if p.get("type", "normal") == "warmup":
                sets.append({**p, "weight_kg": round_to((weight or 0) * 0.5, inc) if weight else p.get("weight_kg"),
                             "reps": p.get("reps_max") or p.get("reps_min") or 8})
                continue
            sets.append({**p, "weight_kg": weight, "reps": reps_for(p, wi)})
            wi += 1
        out.update(sets=sets, reason=reason, action=action)
        return out

    if rule == "none":
        return apply(last_w, lambda p, i: _last_reps(last_work, i) or p.get("reps_max"), "Come l'ultima volta.", "same")

    if rule == "rpe" and last["best_e1rm"]:
        def w_for(p):
            return round_to(_rpe_weight(last["best_e1rm"], p.get("reps_max") or p.get("reps_min") or 5, p.get("rpe") or 8), inc)
        sets, wi = [], 0
        for p in planned:
            if p.get("type", "normal") == "warmup":
                sets.append({**p, "reps": p.get("reps_max") or 5})
                continue
            sets.append({**p, "weight_kg": w_for(p), "reps": p.get("reps_max") or p.get("reps_min")})
            wi += 1
        out.update(sets=sets, action="rpe",
                   reason=f"Dal massimale stimato {fmt_kg(last['best_e1rm'])} kg e RPE {fmt_kg(work_plan[0].get('rpe') if work_plan else 8)}.")
        return out

    reps_min = min((p.get("reps_min") or 0 for p in work_plan), default=0) or None
    reps_max = max((p.get("reps_max") or 0 for p in work_plan), default=0) or None
    done_reps = [s.get("reps") or 0 for s in last_work]
    hit_top = bool(done_reps) and reps_max is not None and len(done_reps) >= len(work_plan) and \
        all(r >= reps_max for r in done_reps[: len(work_plan)])
    hit_min = bool(done_reps) and reps_min is not None and all(r >= reps_min for r in done_reps[: len(work_plan)])
    rpe_ok = all((s.get("rpe") or 0) <= max((p.get("rpe") or 10) for p in work_plan) for s in last_work)

    if rule == "linear":
        fails = _consecutive_misses(history, reps_min or 1)
        if fails >= 2 and last_w:
            new_w = round_to(last_w * 0.9, inc)
            return apply(new_w, lambda p, i: p.get("reps_max") or p.get("reps_min"),
                         f"Due sedute sotto le ripetizioni: si riparte da {fmt_kg(new_w)} kg (-10%).", "reset")
        if hit_min and rpe_ok and not blocked and last_w is not None:
            new_w = round_to(last_w + inc, inc)
            return apply(new_w, lambda p, i: p.get("reps_max") or p.get("reps_min"),
                         f"Riuscito: +{fmt_kg(inc)} kg.", "increase")
        why = "Hai detto che era pesante: stesso peso." if blocked else "Non tutte le ripetizioni: riprova lo stesso peso."
        return apply(last_w, lambda p, i: p.get("reps_max") or p.get("reps_min"), why, "same")

    # double progression (default)
    if hit_top and rpe_ok and not blocked and last_w is not None and inc:
        new_w = round_to(last_w + inc, inc)
        return apply(new_w, lambda p, i: p.get("reps_min") or p.get("reps_max"),
                     f"Tutte le serie a {reps_max}: +{fmt_kg(inc)} kg, riparti da {reps_min}.", "increase")
    if blocked:
        return apply(last_w, lambda p, i: _last_reps(last_work, i) or p.get("reps_min"),
                     "Hai detto che era pesante: stesso peso e stesse ripetizioni.", "same")
    return apply(last_w, lambda p, i: min((_last_reps(last_work, i) or (p.get("reps_min") or 0) - 1) + 1,
                                          p.get("reps_max") or 99),
                 "Stesso peso, una ripetizione in più per serie.", "reps")


def _last_reps(last_work: list[dict], i: int) -> int | None:
    if not last_work:
        return None
    return (last_work[i] if i < len(last_work) else last_work[-1]).get("reps")


def _consecutive_misses(history: list[dict], reps_min: int) -> int:
    n = 0
    for exp in reversed(history):
        work = [d for d in exp["detail"] if d.get("type") in ("normal", "drop", "failure", None)]
        if work and any((d.get("reps") or 0) < reps_min for d in work):
            n += 1
        else:
            break
    return n


def _feedback_blocks(feedback: list[dict], exercise_id: str, since: str | None) -> bool:
    """A 'too heavy' / 'pain' note on this exercise after its last exposure blocks the next increase."""
    for f in feedback:
        if f.get("exercise_id") != exercise_id:
            continue
        if since and (f.get("at") or "") < since:
            continue
        if {"too_heavy", "pain"} & set(f.get("tags") or []):
            return True
    return False


def stall(data: Data, exercise_id: str, exposures_n: int = 3, formula: str = "epley") -> dict | None:
    """No e1RM (or reps, for bodyweight) gain over the last ``exposures_n`` exposures → stalled."""
    hist = exposures(data, exercise_id, formula)
    if len(hist) < exposures_n + 1:
        return None
    metric = "best_e1rm" if any(h["best_e1rm"] for h in hist) else "max_reps"
    before = max((h[metric] or 0) for h in hist[: -exposures_n])
    recent = max((h[metric] or 0) for h in hist[-exposures_n:])
    if recent <= before:
        return {"exercise_id": exercise_id, "since": hist[-exposures_n]["date"], "exposures": exposures_n,
                "best": before, "recent": recent, "metric": metric}
    return None


def warmup(work_weight: float | None, scheme: list[dict] | None, inc: float, bar: float = 20.0) -> list[dict]:
    """Warm-up sets before a working weight (default 40 % × 8, 60 % × 5, 80 % × 3), never below the bar."""
    if not work_weight:
        return []
    scheme = scheme or [{"pct": 40, "reps": 8}, {"pct": 60, "reps": 5}, {"pct": 80, "reps": 3}]
    out = []
    for step in scheme:
        w = max(bar if bar < work_weight else 0, round_to(work_weight * step["pct"] / 100, inc) or 0)
        if w >= work_weight:
            continue
        if out and out[-1]["weight_kg"] == w:
            continue
        out.append({"type": "warmup", "weight_kg": w, "reps": step["reps"]})
    return out


def plates(weight: float, bar: float, available: list[float]) -> dict:
    """Plates per side for a barbell weight (greedy, largest first) and the remainder that can't be loaded."""
    per_side = (weight - bar) / 2
    if per_side <= 0:
        return {"per_side": [], "remainder": 0.0, "loaded": bar}
    left, used = per_side, []
    for p in sorted(available or [25, 20, 15, 10, 5, 2.5, 1.25], reverse=True):
        while left + 1e-9 >= p:
            used.append(p)
            left -= p
    left = round(left, 3)
    return {"per_side": used, "remainder": round(left * 2, 3), "loaded": round(bar + 2 * sum(used), 3)}

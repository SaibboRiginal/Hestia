"""Training goals (SPEC §6.2b): optional, ``{times, per}``, generic first then per template or muscle group."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .catalog import MUSCLE_GROUPS
from .records import Data, is_hard, local_date, period_next, period_start

PER_LABEL = {"day": "oggi", "week": "questa settimana", "month": "questo mese"}


def _counts(data: Data, goal: dict, sessions: list[dict]) -> int:
    scope = goal.get("scope") or "any"
    if scope == "any":
        return len(sessions)
    if scope == "template":
        return sum(1 for s in sessions if s.get("template_id") == goal.get("target_id"))
    muscles = set(MUSCLE_GROUPS.get(goal.get("target_id") or "", [goal.get("target_id")]))
    need = goal.get("min_hard_sets") or 4
    n = 0
    for s in sessions:
        hard = 0.0
        for st in data.sets_by_session.get(s["id"], []):
            if not is_hard(st):
                continue
            ex = data.exercises.get(st["exercise_id"]) or {}
            if set(ex.get("primary_muscles") or []) & muscles:
                hard += 1
            elif set(ex.get("secondary_muscles") or []) & muscles:
                hard += 0.5
        if hard >= need:
            n += 1
    return n


def progress(data: Data, goal: dict, tz, week_start: int = 0, today: date | None = None, history: int = 12) -> dict:
    """Current period done/target, days left, streak of met periods (current one counts once met)."""
    today = today or datetime.now(tz).date()
    per = goal.get("per") or "week"
    by_period: dict[date, list[dict]] = {}
    for s in data.sessions:
        d = local_date(s.get("started_at"), tz)
        if d:
            by_period.setdefault(period_start(d, per, week_start), []).append(s)
    cur = period_start(today, per, week_start)
    done = _counts(data, goal, by_period.get(cur, []))
    times = goal.get("times") or 1
    past, streak, start, counting = [], 0, cur, True
    for i in range(history):
        if i:
            start = period_start(start - timedelta(days=1), per, week_start)
        n = done if i == 0 else _counts(data, goal, by_period.get(start, []))
        met = n >= times
        past.append({"start": start.isoformat(), "done": n, "met": met})
        if i == 0 and not met:
            continue            # the running period doesn't break the streak yet
        if counting and met:
            streak += 1
        elif i > 0:
            counting = False
    days_left = (period_next(cur, per) - today).days
    remaining = max(0, times - done)
    # behind = the rest no longer fits with a free day in between (or it's the last day)
    behind = remaining > 0 and (per == "day" or remaining * 2 - 1 >= days_left)
    return {"goal_id": goal.get("id"), "label": label(goal, data), "done": done, "times": times, "per": per,
            "met": done >= times, "remaining": remaining, "days_left": days_left, "behind": behind,
            "streak": streak, "hint": f"{done}/{times} {PER_LABEL.get(per, '')}".strip(), "history": list(reversed(past))}


def label(goal: dict, data: Data | None = None, templates: dict | None = None) -> str:
    if goal.get("label"):
        return goal["label"]
    per = {"day": "al giorno", "week": "a settimana", "month": "al mese"}.get(goal.get("per") or "week", "")
    times = goal.get("times") or 1
    scope = goal.get("scope") or "any"
    if scope == "any":
        return f"Allenamento {times} {'volta' if times == 1 else 'volte'} {per}"
    if scope == "muscle":
        return f"{(goal.get('target_id') or '').capitalize()} {times} {per}"
    name = (templates or {}).get(goal.get("target_id"), {}).get("name") or "Scheda"
    return f"{name} {times} {per}"

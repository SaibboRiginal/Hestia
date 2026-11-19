"""Adapting today's workout to how I feel (SPEC §5.2) — small rules, each one leaves a trace line.

Input: today's plan (session exercises with planned sets), the exercise catalog, a readiness check-in and
an intent. Output: a modified copy + ``trace`` (Italian, shown as is) + time estimate. Nothing is stored
here: the service applies the result to today's session only when I agree in the conversation.
"""
from __future__ import annotations

import copy
from typing import Any

from .catalog import JOINTS, MUSCLES, MUSCLE_GROUPS
from .progression import round_to
from hestia_common.i18n import languages, t as tr, word_set  # owner language; owner words per language

DEFAULTS = {"low_energy": 2, "weight_cut_pct": 10, "very_low_weight_cut_pct": 15, "work_seconds": 40,
            "setup_seconds": 90, "default_rest": 90, "min_sets_main": 2}

# Words the owner may use: the labels in every language and the plural/colloquial forms of hercules.body.<key>.
_LABELS = {**{tr(v, lang=lang).lower(): k for lang in languages() for names in (JOINTS, MUSCLES) for k, v in names.items()},
           **{w: k for k in (*JOINTS, *MUSCLES) for w in word_set(f"hercules.body.{k}")}}


def resolve_areas(areas: list[str] | None) -> tuple[set[str], set[str]]:
    """Split free words (any language, or keys) into joints and muscles; muscle groups expand to their muscles."""
    joints, muscles = set(), set()
    for raw in areas or []:
        a = str(raw).strip().lower()
        key = _LABELS.get(a, a)
        if key in JOINTS:
            joints.add(key)
        elif key in MUSCLES:
            muscles.add(key)
        elif a in MUSCLE_GROUPS:
            muscles.update(MUSCLE_GROUPS[a])
    return joints, muscles


def estimate_minutes(plan: list[dict], cfg: dict | None = None) -> int:
    cfg = {**DEFAULTS, **(cfg or {})}
    total = 0.0
    for ex in plan:
        if ex.get("skipped"):
            continue
        sets = len(ex.get("planned") or [])
        rest = ex.get("rest_seconds") or cfg["default_rest"]
        total += cfg["setup_seconds"] + sets * cfg["work_seconds"] + max(0, sets - 1) * rest
    return round(total / 60)


def _compound(ex_meta: dict) -> bool:
    return (ex_meta or {}).get("movement_pattern") not in (None, "isolation", "core")


def _alternative(meta: dict, catalog: dict[str, dict], *, avoid_joints: set[str], avoid_equipment: set[str],
                 avoid_muscles: set[str], used: set[str]) -> dict | None:
    """Closest exercise: same primary muscle, same pattern if possible, not loading the avoided joints."""
    prim = set(meta.get("primary_muscles") or [])
    best, best_score = None, -1
    for cand in catalog.values():
        if cand["id"] in used or cand.get("archived") or cand["id"] == meta.get("id"):
            continue
        if set(cand.get("stress_joints") or []) & avoid_joints:
            continue
        if cand.get("equipment") in avoid_equipment:
            continue
        cprim = set(cand.get("primary_muscles") or [])
        if not cprim & prim or cprim & avoid_muscles:
            continue
        same_pattern = cand.get("movement_pattern") == meta.get("movement_pattern")
        if not same_pattern and meta.get("movement_pattern") not in ("isolation", None):
            continue        # a squat is no stand-in for a bench press
        if (cand.get("kind") == "reps_only") != (meta.get("kind") == "reps_only"):
            continue
        score = 3 * len(cprim & prim) + (2 if cand.get("movement_pattern") == meta.get("movement_pattern") else 0) \
            + (1 if cand.get("kind") == meta.get("kind") else 0) + (1 if not cand.get("is_custom") else 0)
        if score > best_score:
            best, best_score = cand, score
    return best


def _scale(ex: dict, pct: float, inc: float, rpe_drop: float = 0) -> None:
    for s in ex.get("planned") or []:
        if s.get("weight_kg"):
            s["weight_kg"] = round_to(s["weight_kg"] * (1 - pct / 100), inc)
        if rpe_drop and s.get("rpe"):
            s["rpe"] = max(5, s["rpe"] - rpe_drop)


def _drop_sets(ex: dict, n: int, keep_min: int = 1) -> int:
    work = [i for i, s in enumerate(ex.get("planned") or []) if s.get("type") != "warmup"]
    removable = max(0, len(work) - keep_min)
    n = min(n, removable)
    for i in reversed(work[-n:] if n else []):
        ex["planned"].pop(i)
    return n


def adapt(plan: list[dict], catalog: dict[str, dict], readiness: dict, *, intent: str = "", cfg: dict | None = None,
          increments: dict | None = None, equipment_missing: list[str] | None = None) -> dict:
    cfg = {**DEFAULTS, **(cfg or {})}
    out = copy.deepcopy(plan)
    trace: list[str] = []
    warnings: list[str] = []
    before = estimate_minutes(out, cfg)
    energy = readiness.get("energy")
    energy = int(energy) if energy not in (None, "") else None
    time_limit = readiness.get("time_minutes")
    intent = (intent or "").strip().lower()
    if intent == "lighter" and (energy is None or energy > cfg["low_energy"]):
        energy = cfg["low_energy"]
    if intent == "shorter" and not time_limit:
        time_limit = max(15, round(before * 0.6))

    def meta(ex):
        return catalog.get(ex.get("exercise_id")) or {}

    def inc(ex):
        from .progression import increment_for
        return increment_for(meta(ex), increments)

    used = {ex.get("exercise_id") for ex in out}

    # 1. pain → never push through: replace or remove what loads it
    pain_j, pain_m = resolve_areas(readiness.get("pain_areas"))
    if pain_j or pain_m:
        for ex in out:
            m = meta(ex)
            hits = (set(m.get("stress_joints") or []) & pain_j) or (set(m.get("primary_muscles") or []) & pain_m)
            if not hits or ex.get("skipped"):
                continue
            alt = _alternative(m, catalog, avoid_joints=pain_j, avoid_equipment=set(equipment_missing or []),
                               avoid_muscles=pain_m, used=used)
            name = m.get("name", "exercise")
            if alt and not (set(alt.get("primary_muscles") or []) & pain_m):
                ex.update(replaced_from=ex["exercise_id"], exercise_id=alt["id"])
                used.add(alt["id"])
                _scale(ex, cfg["weight_cut_pct"], inc(ex))
                for s in ex.get("planned") or []:
                    if alt.get("kind") != m.get("kind"):
                        s["weight_kg"] = None
                trace.append(tr("Pain ({0}): {1} → {2}, lighter load.", ', '.join(tr(JOINTS.get(h, MUSCLES.get(h, h))) for h in hits), name, alt['name']))
            else:
                ex["skipped"] = True
                trace.append(tr("Pain: I remove {0}, no alternative that doesn't load it.", name))
        warnings.append(tr("If the pain comes back often, better see a physiotherapist or a doctor."))

    # 2. equipment missing → same muscle, other equipment
    missing = set(equipment_missing or readiness.get("equipment_missing") or [])
    if missing:
        for ex in out:
            m = meta(ex)
            if ex.get("skipped") or m.get("equipment") not in missing:
                continue
            alt = _alternative(m, catalog, avoid_joints=pain_j, avoid_equipment=missing, avoid_muscles=pain_m, used=used)
            if alt:
                ex.update(replaced_from=ex.get("replaced_from") or ex["exercise_id"], exercise_id=alt["id"])
                used.add(alt["id"])
                for s in ex.get("planned") or []:
                    s["weight_kg"] = None
                trace.append(tr("Without {0}: {1} → {2} (you choose the weight).", m.get('equipment'), m.get('name'), alt['name']))
            else:
                ex["skipped"] = True
                trace.append(tr("Without {0}: I remove {1}.", m.get('equipment'), m.get('name')))

    # 3. soreness → less volume for that muscle
    _, sore = resolve_areas(readiness.get("soreness"))
    if sore:
        for ex in out:
            m = meta(ex)
            if ex.get("skipped") or not set(m.get("primary_muscles") or []) & sore:
                continue
            n = _drop_sets(ex, 1)
            _scale(ex, cfg["weight_cut_pct"], inc(ex))
            trace.append(tr("Soreness: {0} -{1} sets and -{2}% load.", m.get('name'), n, int(cfg['weight_cut_pct'])))

    # 4. energy
    if energy is not None and energy <= cfg["low_energy"]:
        cut = int(cfg["very_low_weight_cut_pct"] if energy <= 1 else cfg["weight_cut_pct"])
        kept_main = 0
        for ex in out:
            if ex.get("skipped"):
                continue
            m = meta(ex)
            main = (ex.get("priority") or 2) == 1 or (_compound(m) and kept_main < 2)
            if main:
                kept_main += 1
                n = _drop_sets(ex, 1, keep_min=cfg["min_sets_main"])
                _scale(ex, cut, inc(ex), rpe_drop=1)
                if n:
                    trace.append(tr("Low energy: {0} -{1} sets, -{2}% load.", m.get('name'), n, cut))
                else:
                    trace.append(tr("Low energy: {0} -{1}% load.", m.get('name'), cut))
            elif energy <= 1 or (ex.get("priority") or 2) >= 3:
                ex["skipped"] = True
                trace.append(tr("Low energy: I skip {0}.", m.get('name')))
            else:
                _drop_sets(ex, 1)
                _scale(ex, cut, inc(ex), rpe_drop=1)
                trace.append(tr("Low energy: {0} one set less.", m.get('name')))
    elif energy is not None and energy >= 4 and intent == "harder":
        for ex in out:
            if not ex.get("skipped") and _compound(meta(ex)):
                work = [s for s in ex.get("planned") or [] if s.get("type") != "warmup"]
                if work:
                    ex["planned"].append(dict(work[-1]))
                    trace.append(tr("Good day: +1 set on {0}.", meta(ex).get('name')))
                break

    # 5. time limit → drop least important first, then trim sets
    if time_limit:
        limit = int(time_limit)
        order = sorted([ex for ex in out if not ex.get("skipped")],
                       key=lambda e: (-(e.get("priority") or 2), 0 if not _compound(meta(e)) else 1,
                                      -out.index(e)))
        for ex in order:
            if estimate_minutes(out, cfg) <= limit:
                break
            if (ex.get("priority") or 2) == 1 or len([e for e in out if not e.get("skipped")]) <= 2:
                continue
            ex["skipped"] = True
            trace.append(tr("You have {0} minutes: I skip {1}.", limit, meta(ex).get('name')))
        guard = 0
        while estimate_minutes(out, cfg) > limit and guard < 50:
            guard += 1
            trimmed = False
            for ex in reversed([e for e in out if not e.get("skipped")]):
                if _drop_sets(ex, 1, keep_min=cfg["min_sets_main"] if _compound(meta(ex)) else 1):
                    trimmed = True
                    break
            if not trimmed:
                break
        if guard:
            trace.append(tr("You have {0} minutes: I remove a few sets at the end.", limit))
        for ex in out:
            if not ex.get("skipped") and ex.get("rest_seconds") and ex["rest_seconds"] > 120:
                ex["rest_seconds"] = 120
        if estimate_minutes(out, cfg) > limit:
            warnings.append(tr("Even so it takes about {0} minutes.", estimate_minutes(out, cfg)))

    if not trace:
        trace.append(tr("No change: the plan is fine as it is."))
    return {"exercises": out, "trace": trace, "warnings": warnings, "minutes_before": before,
            "minutes_after": estimate_minutes(out, cfg), "energy": energy, "intent": intent or None}

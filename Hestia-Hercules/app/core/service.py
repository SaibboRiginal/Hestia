"""Hercules service — what the API, the assistant tools, the UI sync and the agenda job call.

Every write is normalized (``domain``), stored in Archive through the mirror (``store``) and indexed for
statistics (``records``). Engines (``progression``, ``adapt``, ``goals``) are pure; this file wires them.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import adapt as adapt_engine
from . import catalog, domain, goals as goals_engine, importer, progression, records
from .store import Store, StoreUnavailable, now_iso, parse_dt

logger = logging.getLogger("hestia_hercules.service")

WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
WEEK_START_KEY = "themis.personal.week_start"   # personal setting shared by every module (owner Themis)


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail or {}


class Hercules:
    def __init__(self, store: Store, setting: Callable[[str], Any], *, tz_name: str | None = None):
        self.store = store
        self.setting = setting
        self.tz = ZoneInfo(tz_name or os.getenv("TZ") or "Europe/Rome")
        self._data_cache: tuple[int, records.Data] | None = None
        # Weekly plan (hestia_common.coach): ``on_event(event, data)`` with done / skipped / changed. Set by main.
        self.on_event: Callable[[str, dict], None] | None = None

    def _emit(self, event: str, **data) -> None:
        if self.on_event:
            try:
                self.on_event(event, data)
            except Exception as exc:          # the plan never breaks a workout
                logger.warning("[🔄] event=hercules_coach_emit_failed kind=%s error=%s", event, exc)

    # ── basics ──────────────────────────────────────────────────────────────
    def cfg(self, key: str, fallback: Any = None) -> Any:
        try:
            value = self.setting(f"hercules.{key}")
        except Exception:
            value = None
        return fallback if value is None else value

    def today(self) -> date:
        return datetime.now(self.tz).date()

    def week_start_name(self) -> str:
        """Personal setting shared by every module (Themis ``themis.personal.week_start``)."""
        try:
            value = self.setting(WEEK_START_KEY)
        except Exception:
            value = None
        return value or "monday"

    def week_start(self) -> int:
        return 6 if self.week_start_name() == "sunday" else 0

    def formula(self) -> str:
        return self.cfg("e1rm_formula", "epley")

    def increments(self) -> dict:
        return {eq: self.cfg(f"increment.{eq}") for eq in ("barbell", "dumbbell", "machine", "cable")}

    def data(self) -> records.Data:
        self.store.refresh()
        rev = self.store.revision
        if self._data_cache and self._data_cache[0] == rev:
            return self._data_cache[1]
        d = records.Data(self.store.items("session"), self.store.items("set"), self.store.items("exercise"),
                         self.store.items("measurement"))
        self._data_cache = (rev, d)
        return d

    def save(self, kind: str, data: dict, *, id: str | None = None, updated_at: str | None = None) -> dict:
        norm = domain.normalize(kind, data)
        rid = id or data.get("id") or domain.new_id()
        norm.pop("id", None)
        cols = domain.index_columns(kind, norm)
        row = {"kind": kind, "id": rid, "data": norm, **cols}
        if updated_at:
            row["updated_at"] = updated_at
        self.store.write([row])
        if kind in ("goal", "program"):
            self._emit("changed")
        return {**norm, "id": rid}

    def get(self, kind: str, id: str) -> dict:
        self.store.refresh()
        item = self.store.data(kind, id)
        if not item:
            raise NotFound(f"{kind} {id} non trovato")
        return item

    def delete(self, kind: str, id: str) -> dict:
        self.store.refresh()
        if kind == "session":
            for st in self._sets_of(id):
                self.store.delete("set", st["id"])
        if not self.store.delete(kind, id):
            raise NotFound(f"{kind} {id} non trovato")
        return {"deleted": True, "kind": kind, "id": id}

    # ── catalog ─────────────────────────────────────────────────────────────
    def ensure_catalog(self) -> int:
        """Write the built-in exercises that are missing (never touches ones already stored, edited or not)."""
        if not self.store.refresh(force=True):
            return 0
        missing = [e for e in catalog.seed() if not self.store.get("exercise", e["id"], deleted=True)]
        if missing:
            self.store.write([{"kind": "exercise", "id": e["id"], "data": {k: v for k, v in e.items() if k != "id"},
                               "updated_at": "2026-01-01T00:00:00+00:00"} for e in missing])
            logger.info("event=hercules_catalog_seeded added=%d", len(missing))
        return len(missing)

    def exercises(self, q: str = "", muscle: str = "", equipment: str = "", archived: bool = False) -> list[dict]:
        self.store.refresh()
        ql = q.strip().lower()
        group = catalog.MUSCLE_GROUPS.get(muscle)
        data = self.data()
        last_used = {}
        for ex_id, sets in data.sets_by_exercise.items():
            last_used[ex_id] = sets[-1].get("session_at") if sets else None
        out = []
        for e in self.store.items("exercise"):
            if e.get("archived") and not archived:
                continue
            if ql and ql not in e.get("name", "").lower() and not any(ql in a.lower() for a in e.get("aliases") or []):
                continue
            if muscle:
                muscles = set(e.get("primary_muscles") or []) | set(e.get("secondary_muscles") or [])
                if not (muscles & set(group or [muscle])):
                    continue
            if equipment and e.get("equipment") != equipment:
                continue
            out.append({**e, "last_used": last_used.get(e["id"]), "times": len({s["session_id"] for s in
                                                                                data.sets_by_exercise.get(e["id"], [])})})
        def rank(e):
            name = e.get("name", "").lower()
            match = 0 if not ql else (0 if name.startswith(ql) else 1 if f" {ql}" in f" {name}" else 2)
            return (match, not e.get("favorite"), -(e["times"] or 0), len(name), name)
        out.sort(key=rank)
        return out

    def exercise_detail(self, id: str) -> dict:
        ex = self.get("exercise", id)
        data = self.data()
        hist = records.exposures(data, id, self.formula())
        return {"exercise": ex, "records": records.exercise_records(data, id, self.formula()),
                "history": list(reversed(hist[-50:])), "stall": progression.stall(
                    data, id, int(self.cfg("stall.exposures", 3)), self.formula()),
                "increment": progression.increment_for(ex, self.increments()),
                "alternatives": [{"id": a["id"], "name": a["name"]} for a in self._alternatives(ex)]}

    def _alternatives(self, ex: dict, limit: int = 6) -> list[dict]:
        prim = set(ex.get("primary_muscles") or [])
        scored = []
        for c in self.store.items("exercise"):
            if c["id"] == ex["id"] or c.get("archived"):
                continue
            cp = set(c.get("primary_muscles") or [])
            if not cp & prim:
                continue
            scored.append((3 * len(cp & prim) + (2 if c.get("movement_pattern") == ex.get("movement_pattern") else 0), c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:limit]]

    # ── templates and program ───────────────────────────────────────────────
    def templates(self) -> list[dict]:
        self.store.refresh()
        data = self.data()
        last = {}
        for s in data.sessions:
            if s.get("template_id"):
                last[s["template_id"]] = s.get("started_at")
        exs = {e["id"]: e for e in self.store.items("exercise")}
        out = []
        for t in self.store.items("template"):
            if t.get("archived"):
                continue
            plan = self._plan_from_template(t, suggest=False)
            out.append({**t, "last_done": last.get(t["id"]), "estimated_minutes": adapt_engine.estimate_minutes(plan),
                        "muscles": sorted({m for i in t.get("items") or [] for m in
                                           (exs.get(i["exercise_id"]) or {}).get("primary_muscles") or []}),
                        "exercise_names": [(exs.get(i["exercise_id"]) or {}).get("name", "?") for i in t.get("items") or []]})
        out.sort(key=lambda t: (not t.get("favorite"), t.get("folder") or "", t.get("position") or 0, t.get("name")))
        return out

    def template_detail(self, id: str) -> dict:
        t = self.get("template", id)
        data = self.data()
        exs = {e["id"]: e for e in self.store.items("exercise")}
        fb = self.store.items("feedback")
        items = []
        for it in t.get("items") or []:
            ex = exs.get(it["exercise_id"]) or {"id": it["exercise_id"], "name": "?"}
            items.append({**it, "exercise": ex, "suggestion": progression.suggest(
                data, it, ex, formula=self.formula(), increments=self.increments(), feedback=fb)})
        return {**t, "items": items}

    def suggestions(self) -> dict[str, dict]:
        """Next-time targets of every template item (shipped to the UI for offline use)."""
        data = self.data()
        exs = {e["id"]: e for e in self.store.items("exercise")}
        fb = self.store.items("feedback")
        out = {}
        for t in self.store.items("template"):
            for it in t.get("items") or []:
                ex = exs.get(it["exercise_id"])
                if ex:
                    out[it["id"]] = progression.suggest(data, it, ex, formula=self.formula(),
                                                        increments=self.increments(), feedback=fb)
        return out

    def save_template(self, data: dict, *, by_assistant: bool = False) -> dict:
        """Templates keep a light revision history (undo) — the previous version is copied in ``previous``."""
        tid = data.get("id")
        old = self.store.data("template", tid) if tid else None
        body = dict(data)
        if old:
            prev = {k: v for k, v in old.items() if k not in ("previous", "id")}
            body["previous"] = prev
            body["revision"] = int(old.get("revision") or 0) + 1
        if by_assistant:
            body["changed_by"] = "assistant"
        return self.save("template", body, id=tid)

    def undo_template(self, id: str) -> dict:
        t = self.get("template", id)
        prev = t.get("previous")
        if not prev:
            raise Conflict("nessuna versione precedente")
        return self.save("template", {**prev, "revision": int(t.get("revision") or 0) + 1}, id=id)

    def active_program(self) -> dict | None:
        progs = [p for p in self.store.items("program") if p.get("active")]
        return progs[0] if progs else None

    def plans(self, start: date | None = None, days: int = 14) -> list[dict]:
        start = start or self.today() - timedelta(days=7)
        end = start + timedelta(days=days)
        return sorted([p for p in self.store.items("plan") if start.isoformat() <= p.get("date", "") < end.isoformat()],
                      key=lambda p: p["date"])

    def next_workout(self, day: date | None = None) -> dict:
        """What to do next: a day override, else the program, else the least recently done favourite."""
        self.store.refresh()
        day = day or self.today()
        data = self.data()
        templates = {t["id"]: t for t in self.store.items("template") if not t.get("archived")}
        done_today = [s for s in data.sessions if records.local_date(s.get("started_at"), self.tz) == day]
        plans = {p["date"]: p for p in self.store.items("plan")}
        out: dict[str, Any] = {"date": day.isoformat(), "done_today": [records.session_summary(data, s) for s in done_today],
                               "template": None, "reason": "", "program": None, "rest_day": False}
        override = plans.get(day.isoformat())
        if override and override.get("status") == "skipped":
            out.update(reason="Oggi saltato.", skipped=True)
        if override and override.get("status") == "planned" and override.get("template_id") in templates:
            out.update(template=templates[override["template_id"]], reason="Spostato a oggi.")
            return self._with_minutes(out)
        prog = self.active_program()
        if prog and prog.get("days"):
            out["program"] = {"id": prog["id"], "name": prog["name"], "mode": prog["mode"]}
            if prog["mode"] == "weekly":
                for offset in range(0, 7):
                    d = day + timedelta(days=offset)
                    p = plans.get(d.isoformat())
                    if p and p.get("status") in ("skipped", "moved"):
                        continue
                    todays = [x for x in prog["days"] if x.get("weekday") == d.weekday() and x["template_id"] in templates]
                    if not todays:
                        continue
                    if offset == 0 and done_today:
                        continue
                    t = templates[todays[0]["template_id"]]
                    out.update(template=t, planned_date=d.isoformat(),
                               reason="In programma oggi." if offset == 0 else f"Prossimo: {WEEKDAYS[d.weekday()]}.")
                    out["rest_day"] = offset > 0
                    return self._with_minutes(out)
            else:
                order = [x["template_id"] for x in prog["days"] if x["template_id"] in templates]
                last = next((s for s in reversed(data.sessions) if s.get("program_id") == prog["id"]
                             or s.get("template_id") in order), None)
                skips = sum(1 for p in plans.values() if p.get("status") == "skipped" and p.get("rotation_skip")
                            and (not last or p["date"] > (records.local_date(last.get("started_at"), self.tz) or date.min).isoformat()))
                idx = (order.index(last["template_id"]) + 1) if last and last.get("template_id") in order else 0
                if order:
                    t = templates[order[(idx + skips) % len(order)]]
                    out.update(template=t, reason="Prossima della rotazione.")
                    return self._with_minutes(out)
        favs = [t for t in templates.values() if t.get("favorite")] or list(templates.values())
        if favs:
            last_done = {s.get("template_id"): s.get("started_at") for s in data.sessions}
            favs.sort(key=lambda t: last_done.get(t["id"]) or "")
            out.update(template=favs[0], reason="La scheda che non fai da più tempo.")
        return self._with_minutes(out)

    def _with_minutes(self, out: dict) -> dict:
        if out.get("template"):
            out["estimated_minutes"] = adapt_engine.estimate_minutes(self._plan_from_template(out["template"], suggest=False))
        return out

    # ── sessions ────────────────────────────────────────────────────────────
    def _plan_from_template(self, t: dict, *, suggest: bool = True) -> list[dict]:
        data = self.data() if suggest else None
        exs = {e["id"]: e for e in self.store.items("exercise")}
        fb = self.store.items("feedback") if suggest else []
        plan = []
        for it in t.get("items") or []:
            sets = [dict(s) for s in it.get("sets") or []]
            if suggest and exs.get(it["exercise_id"]):
                sug = progression.suggest(data, it, exs[it["exercise_id"]], formula=self.formula(),
                                          increments=self.increments(), feedback=fb)
                sets = [{**p, "weight_kg": s.get("weight_kg"), "reps_target": s.get("reps")}
                        for p, s in zip(sets, sug["sets"])]
            plan.append({"id": domain.new_id(), "exercise_id": it["exercise_id"], "superset": it.get("superset"),
                         "rest_seconds": it.get("rest_seconds"), "notes": it.get("notes", ""),
                         "template_item_id": it.get("id"), "priority": it.get("priority") or 2, "planned": sets})
        return plan

    def active_session(self) -> dict | None:
        self.store.refresh()
        act = [s for s in self.store.items("session") if s.get("status") == "active"]
        act.sort(key=lambda s: s.get("started_at") or "")
        return act[-1] if act else None

    def _sets_of(self, session_id: str) -> list[dict]:
        return sorted([s for s in self.store.items("set") if s.get("session_id") == session_id],
                      key=lambda s: (s.get("position") or 0))

    def start_session(self, template_id: str | None = None, *, name: str = "", plan: list[dict] | None = None,
                      started_at: str | None = None, adaptation_id: str | None = None, readiness: dict | None = None) -> dict:
        current = self.active_session()
        if current:
            raise Conflict("c'è già un allenamento in corso", {"session_id": current["id"], "name": current.get("name")})
        t = self.get("template", template_id) if template_id else None
        exercises = plan if plan is not None else (self._plan_from_template(t) if t else [])
        prog = self.active_program()
        body = {"name": name or (t["name"] if t else "Allenamento libero"), "status": "active",
                "started_at": started_at or now_iso(), "template_id": template_id,
                "program_id": prog["id"] if prog and t and any(d["template_id"] == t["id"] for d in prog["days"]) else None,
                "exercises": exercises, "adaptation_id": adaptation_id, "readiness": readiness or self._today_checkin() or {}}
        return self.session_detail(self.save("session", body)["id"])

    def _today_checkin(self) -> dict | None:
        today = self.today()
        rows = [c for c in self.store.items("checkin") if records.local_date(c.get("at"), self.tz) == today]
        rows.sort(key=lambda c: c.get("at") or "")
        return {k: v for k, v in rows[-1].items() if k not in ("id",)} if rows else None

    def session_detail(self, id: str) -> dict:
        sess = self.get("session", id)
        data = self.data()
        exs = {e["id"]: e for e in self.store.items("exercise")}
        sets = self._sets_of(id)
        blocks = []
        for se in sess.get("exercises") or []:
            ex = exs.get(se["exercise_id"]) or {"id": se["exercise_id"], "name": "?"}
            hist = [h for h in records.exposures(data, se["exercise_id"], self.formula()) if h["session_id"] != id]
            blocks.append({**se, "exercise": ex, "sets": [s for s in sets if s.get("session_exercise_id") == se["id"]],
                           "last": hist[-1] if hist else None,
                           "rest_seconds": se.get("rest_seconds") or self.cfg("rest.default_seconds", 90)})
        done_sets = [s for s in sets if s.get("completed")]
        last_done = max((s.get("completed_at") or "" for s in done_sets), default="")
        rest_until = None
        if last_done and sess.get("status") == "active":
            se_id = next((s["session_exercise_id"] for s in done_sets if s.get("completed_at") == last_done), None)
            rest = next((b["rest_seconds"] for b in blocks if b["id"] == se_id), 90)
            t = parse_dt(last_done)
            if t:
                rest_until = (t + timedelta(seconds=int(rest or 90))).isoformat()
        out = {**sess, "blocks": blocks, "rest_until": rest_until,
               "summary": records.session_summary(data, sess) if sess.get("status") == "done" else None}
        if sess.get("status") == "done":
            out["prs"] = records.session_prs(data, sess, self.formula())
        return out

    def update_session(self, id: str, changes: dict) -> dict:
        sess = self.get("session", id)
        body = {**sess, **{k: v for k, v in changes.items() if k not in ("id", "blocks", "summary", "prs")}}
        self.save("session", body, id=id)
        if "started_at" in changes:
            self._reindex_sets(id, body["started_at"])
        return self.session_detail(id)

    def _reindex_sets(self, session_id: str, started_at: str) -> None:
        rows = []
        for st in self._sets_of(session_id):
            st = {**st, "session_at": started_at}
            sid = st.pop("id")
            rows.append({"kind": "set", "id": sid, "data": st, **domain.index_columns("set", st)})
        self.store.write(rows)

    def add_exercise(self, session_id: str, exercise_id: str, *, replace: str | None = None, sets: int = 3) -> dict:
        sess = self.get("session", session_id)
        self.get("exercise", exercise_id)
        exercises = list(sess.get("exercises") or [])
        if replace:
            for se in exercises:
                if se["id"] == replace:
                    se.update(replaced_from=se["exercise_id"], exercise_id=exercise_id)
                    for s in se.get("planned") or []:
                        s["weight_kg"] = None
        else:
            exercises.append({"id": domain.new_id(), "exercise_id": exercise_id,
                              "planned": [{"type": "normal", "reps_min": 8, "reps_max": 12} for _ in range(sets)]})
        return self.update_session(session_id, {"exercises": exercises})

    def log_set(self, session_id: str, body: dict) -> dict:
        """Log (or update, with ``id``) a set. ``exercise_id`` without ``session_exercise_id`` adds the exercise."""
        sess = self.get("session", session_id)
        se_id = body.get("session_exercise_id")
        if not se_id:
            ex_id = body.get("exercise_id")
            if not ex_id:
                raise domain.Invalid("serve session_exercise_id o exercise_id")
            se = next((e for e in sess.get("exercises") or [] if e["exercise_id"] == ex_id), None)
            if not se:
                self.add_exercise(session_id, ex_id, sets=0)
                sess = self.get("session", session_id)
                se = next(e for e in sess["exercises"] if e["exercise_id"] == ex_id)
            se_id = se["id"]
        se = next((e for e in sess.get("exercises") or [] if e["id"] == se_id), None)
        if not se:
            raise NotFound("esercizio non presente nell'allenamento")
        existing = [s for s in self._sets_of(session_id) if s.get("session_exercise_id") == se_id]
        data = {**body, "session_id": session_id, "session_exercise_id": se_id, "exercise_id": se["exercise_id"],
                "session_at": sess["started_at"]}
        if "position" not in body and not body.get("id"):
            data["position"] = len(existing)
        if data.get("completed", True) and not data.get("completed_at"):
            data["completed_at"] = now_iso()
        return self.save("set", data, id=body.get("id"))

    def log_sets_text(self, session_id: str | None, text: str) -> dict:
        """Natural logging: 'panca 80x8, 80x8, 77.5x7; trazioni 8, 7, 6' (into the active session, or a new one)."""
        import re
        sess = self.get("session", session_id) if session_id else self.active_session()
        if not sess:
            sess = self.start_session(name="Allenamento")
        exs = self.store.items("exercise")
        logged, unknown = [], []
        for part in re.split(r"[;\n]+", text):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^\s*([^\d]+?)\s+([\d].*)$", part)
            if not m:
                unknown.append(part)
                continue
            name, rest = m.group(1).strip(" :-"), m.group(2)
            ex = self._find_exercise(name, exs)
            if not ex:
                unknown.append(name)
                continue
            for chunk in re.split(r"[,\s]+(?=\d)", rest):
                chunk = chunk.strip(" ,")
                if not chunk:
                    continue
                mm = re.match(r"^(\d+(?:[.,]\d+)?)\s*(?:kg)?\s*[x×*]\s*(\d+)(?:\s*[x×*]\s*(\d+))?(?:\s*@\s*(\d+(?:[.,]\d)?))?$", chunk)
                if mm:
                    w, reps, times, rpe = float(mm.group(1).replace(",", ".")), int(mm.group(2)), int(mm.group(3) or 1), mm.group(4)
                    for _ in range(times):
                        logged.append(self.log_set(sess["id"], {"exercise_id": ex["id"], "weight_kg": w, "reps": reps,
                                                                "rpe": float(rpe.replace(",", ".")) if rpe else None}))
                    continue
                mr = re.match(r"^(\d+)$", chunk)
                if mr:
                    logged.append(self.log_set(sess["id"], {"exercise_id": ex["id"], "reps": int(mr.group(1))}))
                else:
                    unknown.append(chunk)
        return {"session_id": sess["id"], "logged": len(logged), "unknown": unknown,
                "session": self.session_detail(sess["id"])}

    def _find_exercise(self, name: str, exs: list[dict]) -> dict | None:
        n = name.lower().strip()
        exact = importer.match_exercise(name, exs)
        if exact:
            return exact
        cands = [e for e in exs if not e.get("archived") and (n in e["name"].lower() or
                                                               any(n in a.lower() for a in e.get("aliases") or []))]
        if not cands:
            return None
        data = self.data()
        cands.sort(key=lambda e: (-len(data.sets_by_exercise.get(e["id"], [])), len(e["name"])))
        return cands[0]

    def finish_session(self, id: str, *, notes: str | None = None, perceived_effort: int | None = None,
                       ended_at: str | None = None, update_template: bool = False) -> dict:
        sess = self.get("session", id)
        changes: dict[str, Any] = {"status": "done", "ended_at": ended_at or sess.get("ended_at") or now_iso()}
        if notes is not None:
            changes["notes"] = notes
        if perceived_effort is not None:
            changes["perceived_effort"] = perceived_effort
        detail = self.update_session(id, changes)
        if update_template and sess.get("template_id"):
            self._template_from_session(sess["template_id"], detail)
        self._emit("done", at=changes["ended_at"])
        return detail

    def _template_from_session(self, template_id: str, detail: dict) -> None:
        t = self.get("template", template_id)
        items = {i["id"]: i for i in t.get("items") or []}
        for b in detail.get("blocks") or []:
            it = items.get(b.get("template_item_id"))
            work = [s for s in b["sets"] if s.get("type") != "warmup" and s.get("completed")]
            if it and work:
                it["sets"] = [{**(it["sets"][i] if i < len(it["sets"]) else it["sets"][-1]), "weight_kg": s.get("weight_kg")}
                              for i, s in enumerate(work)]
        self.save_template({**t, "items": list(items.values())})

    def discard_session(self, id: str) -> dict:
        return self.update_session(id, {"status": "discarded", "ended_at": now_iso()})

    def quick_done(self, template_id: str, *, day: str | None = None) -> dict:
        """'Segna fatto': a done session with the template's suggested values, editable later (undo = delete)."""
        t = self.get("template", template_id)
        when = datetime.now(self.tz)
        if day:
            d = date.fromisoformat(day)
            when = datetime(d.year, d.month, d.day, 18, 0, tzinfo=self.tz)
        plan = self._plan_from_template(t)
        minutes = adapt_engine.estimate_minutes(plan)
        start = (when - timedelta(minutes=minutes)).astimezone(timezone.utc)
        sess = self.save("session", {"name": t["name"], "status": "done", "started_at": start.isoformat(),
                                     "ended_at": when.astimezone(timezone.utc).isoformat(), "template_id": template_id,
                                     "source": "quick", "exercises": plan})
        rows = []
        for se in plan:
            for pos, p in enumerate(se.get("planned") or []):
                st = domain.logged_set({"session_id": sess["id"], "session_exercise_id": se["id"],
                                        "exercise_id": se["exercise_id"], "type": p.get("type", "normal"),
                                        "weight_kg": p.get("weight_kg"), "reps": p.get("reps_target") or p.get("reps_max"),
                                        "position": pos, "completed": True, "completed_at": start.isoformat(),
                                        "session_at": start.isoformat()})
                rows.append({"kind": "set", "id": domain.new_id(), "data": st, **domain.index_columns("set", st)})
        self.store.write(rows)
        self._emit("done", at=when.isoformat())
        return {"session_id": sess["id"], "name": t["name"], "sets": len(rows)}

    # ── days ────────────────────────────────────────────────────────────────
    def skip_day(self, day: str | None = None, note: str = "") -> dict:
        d = day or self.today().isoformat()
        rotation = (self.active_program() or {}).get("mode") == "rotation" and self.cfg("skip_mode", "shift") == "shift"
        existing = next((p for p in self.store.items("plan") if p.get("date") == d), None)
        out = self.save("plan", {"date": d, "status": "skipped", "note": note, "rotation_skip": rotation},
                        id=existing["id"] if existing else None)
        self._emit("skipped", at=f"{d}T12:00:00", reason=note)
        return out

    def unskip_day(self, day: str | None = None) -> dict:
        d = day or self.today().isoformat()
        existing = next((p for p in self.store.items("plan") if p.get("date") == d), None)
        if existing:
            self.store.delete("plan", existing["id"])
        return {"date": d, "status": "restored"}

    def postpone(self, to_day: str, from_day: str | None = None, template_id: str | None = None) -> dict:
        frm = from_day or self.today().isoformat()
        nxt = self.next_workout(date.fromisoformat(frm))
        tid = template_id or (nxt.get("template") or {}).get("id")
        if not tid:
            raise Conflict("niente da spostare")
        plans = {p["date"]: p for p in self.store.items("plan")}
        self.save("plan", {"date": frm, "status": "moved", "template_id": tid, "note": f"spostato al {to_day}"},
                  id=(plans.get(frm) or {}).get("id"))
        out = self.save("plan", {"date": to_day, "status": "planned", "template_id": tid, "from_date": frm},
                        id=(plans.get(to_day) or {}).get("id"))
        self._emit("changed")
        return out

    # ── how I feel ──────────────────────────────────────────────────────────
    def checkin(self, body: dict) -> dict:
        row = self.save("checkin", {**body, "at": body.get("at") or now_iso()})
        act = self.active_session()
        if act:
            self.update_session(act["id"], {"readiness": {k: row.get(k) for k in ("energy", "sleep", "soreness", "stress",
                                                                                     "pain_areas", "time_minutes", "free_text")}})
        return row

    def feedback(self, body: dict) -> dict:
        return self.save("feedback", {**body, "at": body.get("at") or now_iso()})

    def adapt_today(self, readiness: dict | None = None, *, intent: str = "", equipment_missing: list | None = None,
                    template_id: str | None = None) -> dict:
        """Preview of today's adjusted plan (stored as an adaptation, not applied)."""
        readiness = {**(self._today_checkin() or {}), **(readiness or {})}
        act = self.active_session()
        if act and not template_id:
            logged = {s["session_exercise_id"] for s in self._sets_of(act["id"])}
            plan = [e for e in act.get("exercises") or [] if e["id"] not in logged]
            base = {"session_id": act["id"], "template_id": act.get("template_id"), "name": act.get("name")}
        else:
            t = self.get("template", template_id) if template_id else (self.next_workout().get("template"))
            if not t:
                raise Conflict("nessuna scheda da adattare: crea una scheda o un programma")
            plan = self._plan_from_template(t)
            base = {"session_id": None, "template_id": t["id"], "name": t["name"]}
        catalog_map = {e["id"]: e for e in self.store.items("exercise")}
        cfg = {"low_energy": int(self.cfg("adapt.low_energy", 2)), "weight_cut_pct": float(self.cfg("adapt.weight_cut_pct", 10)),
               "default_rest": int(self.cfg("rest.default_seconds", 90))}
        result = adapt_engine.adapt(plan, catalog_map, readiness, intent=intent, cfg=cfg, increments=self.increments(),
                                    equipment_missing=equipment_missing)
        pain_count = self._recent_pain(readiness)
        if pain_count >= 3:
            result["warnings"].append(f"È la {pain_count}ª volta in due settimane che segnali dolore: fatti vedere.")
        adaptation = self.save("adaptation", {**base, "created_at": now_iso(), "readiness": readiness, "intent": intent,
                                              "original": plan, "result": result, "accepted": False})
        names = {e["id"]: e.get("name") for e in catalog_map.values()}
        return {"adaptation_id": adaptation["id"], **base, **result,
                "plan_text": [f"{names.get(e['exercise_id'], '?')}: {len(e.get('planned') or [])} serie"
                              for e in result["exercises"] if not e.get("skipped")]}

    def _recent_pain(self, readiness: dict) -> int:
        since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        n = sum(1 for c in self.store.items("checkin") if (c.get("at") or "") >= since and c.get("pain_areas"))
        n += sum(1 for f in self.store.items("feedback") if (f.get("at") or "") >= since and "pain" in (f.get("tags") or []))
        return n + (1 if readiness.get("pain_areas") else 0)

    def apply_adaptation(self, adaptation_id: str) -> dict:
        a = self.get("adaptation", adaptation_id)
        exercises = [e for e in a["result"]["exercises"] if not e.get("skipped")]
        if a.get("session_id"):
            sess = self.get("session", a["session_id"])
            logged = {s["session_exercise_id"] for s in self._sets_of(sess["id"])}
            kept = [e for e in sess.get("exercises") or [] if e["id"] in logged]
            detail = self.update_session(sess["id"], {"exercises": kept + exercises, "adaptation_id": adaptation_id,
                                                       "original_plan": a.get("original")})
        else:
            detail = self.start_session(a.get("template_id"), plan=exercises, adaptation_id=adaptation_id,
                                        readiness=a.get("readiness"))
            self.update_session(detail["id"], {"original_plan": a.get("original")})
        self.save("adaptation", {**a, "accepted": True, "session_id": detail["id"]}, id=adaptation_id)
        return detail

    def restore_today(self, session_id: str | None = None) -> dict:
        sess = self.get("session", session_id) if session_id else self.active_session()
        if not sess or not sess.get("original_plan"):
            raise Conflict("niente da ripristinare")
        logged = {s["session_exercise_id"] for s in self._sets_of(sess["id"])}
        kept = [e for e in sess.get("exercises") or [] if e["id"] in logged]
        done_items = {e.get("template_item_id") for e in kept}
        rest = [e for e in sess["original_plan"] if e.get("template_item_id") not in done_items]
        return self.update_session(sess["id"], {"exercises": kept + rest, "adaptation_id": None, "original_plan": None})

    # ── body ────────────────────────────────────────────────────────────────
    def measurements(self, kind: str = "", days: int = 365) -> list[dict]:
        self.store.refresh()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = [m for m in self.store.items("measurement") if (not kind or m.get("kind") == kind)
                and (m.get("taken_at") or "") >= since]
        return sorted(rows, key=lambda m: m.get("taken_at") or "")

    def log_measurement(self, kind: str, value: float, taken_at: str | None = None, unit: str = "") -> dict:
        return self.save("measurement", {"kind": kind, "value": value, "unit": unit, "taken_at": taken_at or now_iso()})

    # ── statistics ──────────────────────────────────────────────────────────
    def stats(self, per: str = "week", count: int = 12) -> dict:
        data = self.data()
        count = max(1, min(int(count), 104))
        return {"per": per, "periods": records.periods(data, per, count, self.tz, self.week_start()),
                "recent_prs": records.recent_prs(data, 30, self.formula()),
                "totals": {"sessions": len(data.sessions),
                           "since": data.sessions[0].get("started_at") if data.sessions else None},
                "heatmap": records.heatmap(data, 371, self.tz)}

    def history(self, *, days: int = 90, exercise_id: str = "", template_id: str = "", limit: int = 100,
                before: str | None = None) -> list[dict]:
        data = self.data()
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days else ""
        out = []
        for s in reversed(data.sessions):
            if before and (s.get("started_at") or "") >= before:
                continue
            if since and (s.get("started_at") or "") < since:
                break
            if template_id and s.get("template_id") != template_id:
                continue
            if exercise_id and not any(st["exercise_id"] == exercise_id for st in data.sets_by_session.get(s["id"], [])):
                continue
            out.append(records.session_summary(data, s))
            if len(out) >= limit:
                break
        return out

    # ── goals ───────────────────────────────────────────────────────────────
    def goals(self) -> list[dict]:
        data = self.data()
        templates = {t["id"]: t for t in self.store.items("template")}
        out = []
        for g in self.store.items("goal"):
            if not g.get("active", True):
                continue
            p = goals_engine.progress(data, g, self.tz, self.week_start())
            p["label"] = goals_engine.label(g, data, templates)
            out.append({**g, "progress": p})
        return out

    # ── quick actions (Home chips) ──────────────────────────────────────────
    def quick_chips(self) -> list[dict]:
        self.store.refresh()
        data = self.data()
        today = self.today()
        act = self.active_session()
        goals = self.goals()
        hint = goals[0]["progress"]["hint"] if goals else ""
        chips = []
        if act:
            chips.append({"id": f"resume:{act['id']}", "label": f"Riprendi {act.get('name')}", "icon": "play",
                          "state": "todo", "hint": "in corso"})
        favs = [t for t in self.store.items("template") if t.get("favorite") and not t.get("archived")]
        nxt = self.next_workout()
        if nxt.get("template") and nxt["template"]["id"] not in {t["id"] for t in favs}:
            favs.insert(0, nxt["template"])
        done_today = {s.get("template_id") for s in data.sessions if records.local_date(s.get("started_at"), self.tz) == today}
        for t in favs[:6]:
            chips.append({"id": t["id"], "label": t["name"], "icon": "dumbbell", "favorite": bool(t.get("favorite")),
                          "state": "done" if t["id"] in done_today else ("late" if goals and goals[0]["progress"]["behind"]
                                                                         else "todo"), "hint": hint})
        return chips

    # ── assistant ───────────────────────────────────────────────────────────
    def summary(self) -> dict:
        """Week at a glance for the assistant (also the module context line)."""
        self.store.refresh()
        data = self.data()
        nxt = self.next_workout()
        week = records.periods(data, "week", 2, self.tz, self.week_start())
        goals = self.goals()
        prs = records.recent_prs(data, 14, self.formula(), limit=3)
        stalls = []
        for ex_id in list(data.sets_by_exercise)[:200]:
            s = progression.stall(data, ex_id, int(self.cfg("stall.exposures", 3)), self.formula())
            if s:
                s["exercise"] = (data.exercises.get(ex_id) or {}).get("name")
                stalls.append(s)
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        low = [c for c in self.store.items("checkin") if (c.get("at") or "") >= since and (c.get("energy") or 5) <= 2]
        last = data.sessions[-1] if data.sessions else None
        act = self.active_session()
        skipped = [p for p in self.plans(self.today() - timedelta(days=7), 8) if p.get("status") == "skipped"]
        missed = self._missed_days(7)
        flags = []
        if len(low) >= 3:
            flags.append("deload_suggested")
        if stalls:
            flags.append("stall")
        lines = []
        if act:
            lines.append(f"In corso: {act.get('name')}")
        if nxt.get("template"):
            lines.append(f"{'Oggi' if not nxt.get('rest_day') else 'Prossimo'}: {nxt['template']['name']}"
                         f" · {nxt.get('estimated_minutes', '?')} min")
        if goals:
            g = goals[0]["progress"]
            lines.append(f"{g['label']}: {g['hint']}" + (" (indietro)" if g["behind"] else ""))
        else:
            lines.append(f"Settimana: {week[-1]['sessions']} allenamenti")
        if prs:
            lines.append("PR: " + ", ".join(f"{p['exercise']} {p['label'].lower()} {progression.fmt_kg(p['value'])}" for p in prs))
        if stalls:
            lines.append("Stallo: " + ", ".join(s["exercise"] for s in stalls[:3]))
        if "deload_suggested" in flags:
            lines.append("Energia bassa 3+ volte in 7 giorni: valuta una settimana di scarico")
        if missed:
            lines.append("Saltati: " + ", ".join(missed))
        if last:
            lines.append(f"Ultimo: {last.get('name')} {records.local_date(last.get('started_at'), self.tz)}")
        return {"text": " · ".join(lines), "lines": lines, "next": nxt, "week": week[-1], "previous_week": week[0],
                "goals": [{"label": g["progress"]["label"], **{k: g["progress"][k] for k in ("done", "times", "behind", "streak")}}
                          for g in goals],
                "recent_prs": prs, "stalls": stalls[:5], "low_energy_checkins_7d": len(low), "flags": flags,
                "skipped_7d": [p["date"] for p in skipped], "missed_7d": missed,
                "active_session": {"id": act["id"], "name": act.get("name")} if act else None,
                "last_sync": self.store.cursor}

    def _missed_days(self, days: int) -> list[str]:
        """Program days in the last ``days`` (before today) with no session, not skipped/moved."""
        prog = self.active_program()
        if not prog or prog.get("mode") != "weekly":
            return []
        data = self.data()
        done = {records.local_date(s.get("started_at"), self.tz) for s in data.sessions}
        plans = {p["date"]: p for p in self.store.items("plan")}
        out = []
        for i in range(days, 0, -1):
            d = self.today() - timedelta(days=i)
            if any(x.get("weekday") == d.weekday() for x in prog["days"]) and d not in done \
                    and (plans.get(d.isoformat()) or {}).get("status") not in ("skipped", "moved"):
                out.append(f"{WEEKDAYS[d.weekday()]} {d.day}")
        return out

    # ── sync (offline UI) ───────────────────────────────────────────────────
    BOOT_KINDS = ("exercise", "template", "program", "goal", "plan", "measurement", "checkin", "feedback")

    def bootstrap(self, days: int = 120) -> dict:
        """Everything the UI needs offline: catalog, templates, program, goals, plans, recent sessions and sets."""
        self.store.refresh(force=True)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = []
        for (kind, _), r in self.store.rows.items():
            if r.get("deleted"):
                continue
            if kind in self.BOOT_KINDS or (kind in ("session", "set") and ((r.get("at") or "") >= since
                                                                          or r["data"].get("status") == "active")):
                rows.append(self._wire(r))
        return {"cursor": self.store.cursor, "rows": rows, "suggestions": self.suggestions(),
                "settings": self.client_settings(), "server_time": now_iso()}

    def client_settings(self) -> dict:
        return {"units": self.cfg("units", "kg"), "rest_default": self.cfg("rest.default_seconds", 90),
                "bar_weight": self.cfg("bar_weight", 20), "plates": self.cfg("plates", [25, 20, 15, 10, 5, 2.5, 1.25]),
                "increments": {**progression.DEFAULT_INCREMENTS, **{k: v for k, v in self.increments().items() if v}},
                "e1rm_formula": self.formula(), "week_start": self.week_start_name(),
                "warmup": self.warmup_scheme()}

    def warmup_scheme(self) -> list[dict]:
        """Setting '40x8,60x5,80x3' → [{pct, reps}]; anything unreadable → the default scheme."""
        raw = self.cfg("warmup.scheme", "40x8,60x5,80x3")
        out = []
        for part in str(raw).split(","):
            try:
                pct, reps = part.lower().replace("%", "").split("x")
                out.append({"pct": float(pct), "reps": int(reps)})
            except ValueError:
                continue
        return out or [{"pct": 40, "reps": 8}, {"pct": 60, "reps": 5}, {"pct": 80, "reps": 3}]

    @staticmethod
    def _wire(r: dict) -> dict:
        return {"kind": r["kind"], "id": r["id"], "data": r.get("data") or {}, "updated_at": r.get("updated_at"),
                "deleted": bool(r.get("deleted")), "seq": r.get("seq")}

    def sync(self, device_id: str, cursor: int, ops: list[dict]) -> dict:
        """Apply the device's outbox (idempotent, last write wins) and return what changed since its cursor."""
        rows, rejected = [], []
        for op in ops or []:
            kind, rid = op.get("kind"), op.get("id")
            try:
                if kind not in domain.NORMALIZERS or kind in ("adaptation", "reminder"):
                    raise domain.Invalid(f"tipo sconosciuto: {kind}")
                if not rid:
                    raise domain.Invalid("id mancante")
                updated = op.get("updated_at") or now_iso()
                if op.get("action") == "delete":
                    cur = self.store.get(kind, rid, deleted=True)
                    base = cur or {"kind": kind, "id": rid, "data": op.get("fields") or {}}
                    rows.append({"kind": kind, "id": rid, "parent_id": base.get("parent_id"), "ref_id": base.get("ref_id"),
                                 "at": base.get("at"), "data": base.get("data") or {}, "deleted": True, "updated_at": updated})
                    continue
                data = domain.normalize(kind, op.get("fields") or {})
                data.pop("id", None)
                if kind == "set" and not data.get("session_at"):
                    sess = self.store.data("session", data["session_id"]) or \
                        next(((o.get("fields") or {}) for o in ops if o.get("kind") == "session" and o.get("id") == data["session_id"]), {})
                    data["session_at"] = sess.get("started_at")
                rows.append({"kind": kind, "id": rid, "data": data, "updated_at": updated,
                             **domain.index_columns(kind, data)})
            except domain.Invalid as exc:
                rejected.append({"op_id": op.get("op_id"), "kind": kind, "id": rid, "error": str(exc)})
        self.store.refresh(force=True)
        was_done = {r["id"] for r in rows if r["kind"] == "session"
                    and (self.store.data("session", r["id"]) or {}).get("status") == "done"}
        result = self.store.write(rows) if rows else {"applied": [], "stale": []}
        applied_keys = {(a["kind"], a["id"]) for a in result.get("applied") or []}
        stale_keys = {(s["kind"], s["id"]) for s in result.get("stale") or []}
        op_ids = {(o.get("kind"), o.get("id")): o.get("op_id") for o in ops or []}
        for r in rows:
            if r["kind"] == "session" and not r.get("deleted") and (r["data"] or {}).get("status") == "done" \
                    and (r["kind"], r["id"]) in applied_keys and r["id"] not in was_done:
                self._emit("done", at=r["data"].get("ended_at") or r["data"].get("started_at"))
        changes = [self._wire(r) for r in self.store.changes_since(int(cursor or 0))]
        logger.info("event=hercules_sync device=%s ops=%d applied=%d stale=%d rejected=%d changes=%d",
                    device_id or "?", len(ops or []), len(applied_keys), len(stale_keys), len(rejected), len(changes))
        return {"applied": [op_ids.get(k) for k in applied_keys | stale_keys if op_ids.get(k)],
                "rejected": rejected, "stale": [self._wire(s) for s in result.get("stale") or []],
                "changes": changes, "cursor": self.store.cursor,
                "suggestions": self.suggestions() if rows or changes else None, "server_time": now_iso()}

    # ── import / export ─────────────────────────────────────────────────────
    def import_preview(self, text: str, unit: str = "kg") -> dict:
        self.store.refresh()
        return importer.preview(text, self.store.items("exercise"), self.tz, unit)

    def import_commit(self, text: str, mapping: dict[str, str], unit: str = "kg") -> dict:
        self.store.refresh()
        built = importer.build(text, mapping or {}, self.store.items("exercise"), self.tz, unit)
        rows = []
        for e in built["exercises"]:
            data = domain.normalize("exercise", e)
            rows.append({"kind": "exercise", "id": e["id"], "data": {k: v for k, v in data.items() if k != "id"}})
        for s in built["sessions"]:
            data = domain.normalize("session", s)
            rows.append({"kind": "session", "id": s["id"], "data": {k: v for k, v in data.items() if k != "id"},
                         **domain.index_columns("session", data)})
        for st in built["sets"]:
            data = domain.normalize("set", st)
            rows.append({"kind": "set", "id": st["id"], "data": {k: v for k, v in data.items() if k != "id"},
                         **domain.index_columns("set", data)})
        self.store.write(rows)
        return {"exercises_created": len(built["exercises"]), "sessions": len(built["sessions"]), "sets": len(built["sets"])}

    def export(self, fmt: str = "csv") -> tuple[str, str]:
        self.store.refresh(force=True)
        if fmt == "json":
            import json
            rows = [self._wire(r) for r in self.store.rows.values() if not r.get("deleted")]
            return json.dumps({"exported_at": now_iso(), "rows": rows}, ensure_ascii=False), "application/json"
        exs = {e["id"]: e for e in self.store.items("exercise")}
        return importer.export_csv(self.store.items("session"), self.store.items("set"), exs), "text/csv"

    # ── reminder (agenda job, off by default) ───────────────────────────────
    def reminder_decision(self) -> dict:
        """Whether to nudge now: enabled, a goal behind, nothing done today, under the weekly cap."""
        if not self.cfg("reminder.enabled", False):
            return {"send": False, "why": "disabled"}
        goals = self.goals()
        behind = [g for g in goals if g["progress"]["behind"]]
        if not behind:
            return {"send": False, "why": "on_track" if goals else "no_goal"}
        data = self.data()
        if any(records.local_date(s.get("started_at"), self.tz) == self.today() for s in data.sessions):
            return {"send": False, "why": "done_today"}
        if self.active_session():
            return {"send": False, "why": "in_progress"}
        if any(p.get("date") == self.today().isoformat() and p.get("status") in ("skipped", "moved")
               for p in self.store.items("plan")):
            return {"send": False, "why": "skipped_today"}
        week0 = records.period_start(self.today(), "week", self.week_start())
        sent = [r for r in self.store.items("reminder") if (records.local_date(r.get("at"), self.tz) or date.min) >= week0]
        if any(records.local_date(r.get("at"), self.tz) == self.today() for r in sent):
            return {"send": False, "why": "sent_today"}       # one nudge a day, like every module
        if len(sent) >= int(self.cfg("reminder.max_per_week", 2)):
            return {"send": False, "why": "weekly_cap"}
        return {"send": True, "goal": behind[0]["progress"], "next": self.next_workout()}

    def mark_reminder_sent(self) -> None:
        # a tiny marker row keeps the weekly cap across restarts
        self.store.write([{"kind": "reminder", "id": domain.new_id(), "at": now_iso(), "data": {"at": now_iso()}}])

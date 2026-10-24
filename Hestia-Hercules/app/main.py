"""Hestia-Hercules — gym coach: workout tracking, records, progression and adaptation (domain ``fitness``).

SPEC docs/work/2026-10-17-coach-module. Data in Archive (``/api/hercules-store``), settings in Themis, reminders
through the agenda (Chronos) and Hermes, UI as a plugin bundle (``ui/``), assistant tools over MCP.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

import requests
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common import recap
from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.coach import CoachClient, CoachRouter
from hestia_common.plugin_client import PluginClient, page, quick_action, widget
from hestia_common.reminders import reminder_event, reminder_settings, voice_setting
from hestia_common.transfer import StoreSection, Transfer
from hestia_common.settings_client import SettingsClient, setting
from hestia_common.signals_client import Signals, signals_rule

from .core import catalog, domain
from .core.activities import Activities
from .core.coach import HerculesCoach
from .core.hub import Hub
from .core.service import Conflict, Hercules, NotFound
from .core.store import Store, StoreUnavailable, now_iso

logger, log_buffer = setup_service_logging("hestia_hercules")

SERVICE_NAME = os.getenv("SERVICE_NAME", "hercules")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_hercules:19019")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "module")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "module,fitness,context,coach").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:domain,domain:fitness,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
UI_DIST = os.getenv("HERCULES_UI_DIST", "/code/ui/dist")
API = "/api/hercules"
TZ = os.getenv("TZ") or "Europe/Rome"

# ── settings (Themis) ────────────────────────────────────────────────────────
settings = SettingsClient("hercules")
settings.declare([
    setting("hercules.units", "Unità di peso", "enum", "kg", group="Generale", options=[("kg", "kg"), ("lb", "lb")],
            help="Come vedo i pesi. Nel database sono sempre in kg."),
    setting("hercules.rest.default_seconds", "Recupero predefinito", "int", 90, group="Allenamento", min=15, max=600,
            unit="s", help="Timer di recupero quando l'esercizio non ne ha uno suo."),
    setting("hercules.bar_weight", "Peso del bilanciere", "float", 20, group="Allenamento", min=0, max=50, unit="kg"),
    setting("hercules.plates", "Dischi disponibili", "list", [25, 20, 15, 10, 5, 2.5, 1.25], group="Allenamento",
            help="Per il calcolatore dei dischi (kg per disco)."),
    setting("hercules.warmup.scheme", "Riscaldamento", "string", "40x8,60x5,80x3", group="Allenamento",
            help="Percentuale × ripetizioni del peso di lavoro, separati da virgola."),
    setting("hercules.increment.barbell", "Incremento bilanciere", "float", 2.5, group="Progressione", min=0, max=20, unit="kg"),
    setting("hercules.increment.dumbbell", "Incremento manubri", "float", 2.0, group="Progressione", min=0, max=20, unit="kg"),
    setting("hercules.increment.machine", "Incremento macchine", "float", 5.0, group="Progressione", min=0, max=20, unit="kg"),
    setting("hercules.increment.cable", "Incremento cavi", "float", 2.5, group="Progressione", min=0, max=20, unit="kg"),
    setting("hercules.e1rm_formula", "Formula massimale stimato", "enum", "epley", group="Progressione",
            options=[("epley", "Epley"), ("brzycki", "Brzycki")]),
    setting("hercules.stall.exposures", "Sedute per lo stallo", "int", 3, group="Progressione", min=2, max=10,
            help="Dopo quante sedute senza miglioramenti segnalo uno stallo."),
    setting("hercules.adapt.low_energy", "Soglia energia bassa", "int", 2, group="Adattamento", min=1, max=4,
            help="Energia (1–5) a cui alleggerisco l'allenamento."),
    setting("hercules.adapt.weight_cut_pct", "Riduzione carico", "int", 10, group="Adattamento", min=0, max=40, unit="%"),
    setting("hercules.skip_mode", "Giorno saltato", "enum", "shift", group="Programma",
            options=[("shift", "La rotazione slitta"), ("keep", "Si passa alla scheda successiva")],
            help="Vale per i programmi a rotazione; quelli settimanali seguono il calendario."),
    setting("hercules.coach.time_of_day", "Quando allenarmi nel piano", "enum", "evening", group="Piano della settimana",
            options=[("morning", "Mattina"), ("midday", "Pausa pranzo"), ("afternoon", "Pomeriggio"),
                     ("evening", "Sera"), ("any", "Quando c'è tempo")],
            help="Parte del giorno in cui il piano della settimana mette gli allenamenti."),
    setting("hercules.coach.min_minutes", "Allenamento più corto accettabile", "int", 30, group="Piano della settimana",
            min=10, max=120, unit="min",
            help="Se un giorno ha poco tempo libero il piano usa una versione corta, ma non sotto questi minuti."),
    *reminder_settings("hercules", help="Solo se sei indietro con l'obiettivo e oggi non ti sei allenato. Uno alla volta."),
    voice_setting("hercules", True),
]).follow_personal()                                       # week start: personal setting shared by every module

hub = Hub(HUB_API_URL)
store = Store(hub)
hercules = Hercules(store, settings.get)
agenda = AgendaClient("hercules", HUB_API_URL)
activities = Activities(hercules, hub.call, agenda, api=API)
# reflection signals (Archive signals-store): re-evaluated after the natural writes and by the daily agenda job
signals = Signals("hercules", "fitness", evaluate=hercules.signals, hub_api_url=HUB_API_URL)
coach = HerculesCoach(hercules)
coach_client = CoachClient("hercules", HUB_API_URL)


def _coach_event(event: str, data: dict) -> None:
    """Tell the weekly plan (Chronos) in the background: a workout never waits on the network."""
    def _send():
        if event == "done":
            coach_client.done("workout", data.get("at"))
        elif event == "skipped":
            coach_client.skipped("workout", data.get("at"), data.get("reason") or "")
        else:
            coach_client.changed()
    threading.Thread(target=_send, daemon=True, name=f"hercules-coach-{event}").start()


hercules.on_event = _coach_event

app = FastAPI(title="Hestia-Hercules", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
def _needs(start, end) -> dict:
    """Gym needs + open outdoor intentions (tag ``outdoor``: the weekly plan avoids rain for them)."""
    out = coach.needs(start, end)
    try:
        out["needs"] = [*out["needs"], *activities.coach_needs(start, end)]
    except Exception as exc:
        logger.warning("[🔄] event=hercules_activity_needs_failed error=%s fallback=gym_only", exc)
    return out


def _activity_event(event: str, need_id: str, at: str | None) -> None:
    def _send():
        if event == "done":
            coach_client.done(need_id, at)
        else:
            coach_client.changed()
    threading.Thread(target=_send, daemon=True, name=f"hercules-activity-{event}").start()


activities.on_event = _activity_event
app.include_router(CoachRouter("hercules", "fitness", "Allenamento", needs=_needs, fit=coach.fit,
                               placed=coach.on_placed, review=coach.review).router)


@app.exception_handler(domain.Invalid)
async def _invalid(_: Request, exc: domain.Invalid):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Conflict)
async def _conflict(_: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={"detail": str(exc), **exc.detail})


@app.exception_handler(StoreUnavailable)
async def _store_down(_: Request, exc: StoreUnavailable):
    return JSONResponse(status_code=503, content={"detail": "archivio non raggiungibile, riprova (i dati offline restano sul telefono)"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hercules", "version": SERVICE_VERSION, "mirror_loaded": store.loaded,
            "rows": len(store.rows), "cursor": store.cursor}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    logs = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_hercules", "count": len(logs), "logs": logs}


# ── offline sync ─────────────────────────────────────────────────────────────
@app.get(f"{API}/bootstrap")
def bootstrap(days: int = 120):
    return hercules.bootstrap(days)


@app.post(f"{API}/sync")
def sync(body: dict = Body(...)):
    out = hercules.sync(str(body.get("device_id") or ""), int(body.get("cursor") or 0), body.get("ops") or [])
    if body.get("ops"):
        signals.changed()
    return out


@app.get(f"{API}/meta")
def meta():
    """Labels for the UI (muscles, groups, joints, equipment, kinds, patterns)."""
    return {"muscles": catalog.MUSCLES, "groups": catalog.MUSCLE_GROUPS, "joints": catalog.JOINTS,
            "equipment": catalog.EQUIPMENT, "kinds": catalog.KINDS, "patterns": catalog.PATTERNS,
            "measurements": domain.MEASUREMENTS, "feedback_tags": list(domain.FEEDBACK_TAGS)}


# ── exercises ────────────────────────────────────────────────────────────────
@app.get(f"{API}/exercises")
def exercises(q: str = "", muscle: str = "", equipment: str = "", archived: bool = False, limit: int = 300):
    items = hercules.exercises(q, muscle, equipment, archived)
    return {"count": len(items), "items": items[: max(1, min(limit, 1000))]}


@app.post(f"{API}/exercises")
def exercise_create(body: dict = Body(...)):
    return hercules.save("exercise", {**body, "is_custom": body.get("is_custom", True)})


@app.get(f"{API}/exercises/{{id}}")
def exercise_get(id: str):
    return hercules.exercise_detail(id)


@app.put(f"{API}/exercises/{{id}}")
def exercise_update(id: str, body: dict = Body(...)):
    current = hercules.get("exercise", id)
    return hercules.save("exercise", {**current, **body}, id=id)


@app.delete(f"{API}/exercises/{{id}}")
def exercise_archive(id: str):
    current = hercules.get("exercise", id)
    return hercules.save("exercise", {**current, "archived": True}, id=id)


# ── templates & programs ─────────────────────────────────────────────────────
@app.get(f"{API}/templates")
def templates():
    return {"items": hercules.templates()}


@app.post(f"{API}/templates")
def template_create(body: dict = Body(...)):
    return hercules.save_template(body)


@app.get(f"{API}/templates/{{id}}")
def template_get(id: str):
    return hercules.template_detail(id)


@app.put(f"{API}/templates/{{id}}")
def template_update(id: str, body: dict = Body(...)):
    return hercules.save_template({**hercules.get("template", id), **body, "id": id},
                                  by_assistant=bool(body.get("by_assistant")))


@app.delete(f"{API}/templates/{{id}}")
def template_delete(id: str):
    return hercules.save_template({**hercules.get("template", id), "archived": True, "id": id})


@app.post(f"{API}/templates/{{id}}/undo")
def template_undo(id: str):
    return hercules.undo_template(id)


@app.get(f"{API}/programs")
def programs():
    return {"items": hercules.store.items("program"), "active": hercules.active_program()}


@app.post(f"{API}/programs")
def program_create(body: dict = Body(...)):
    return _save_program(body)


@app.put(f"{API}/programs/{{id}}")
def program_update(id: str, body: dict = Body(...)):
    return _save_program({**hercules.get("program", id), **body, "id": id})


@app.delete(f"{API}/programs/{{id}}")
def program_delete(id: str):
    return hercules.delete("program", id)


def _save_program(body: dict) -> dict:
    saved = hercules.save("program", body, id=body.get("id"))
    if saved.get("active"):     # one active program at a time
        for p in hercules.store.items("program"):
            if p["id"] != saved["id"] and p.get("active"):
                hercules.save("program", {**p, "active": False}, id=p["id"])
    return saved


@app.get(f"{API}/next")
def next_workout():
    return hercules.next_workout()


# ── sessions ─────────────────────────────────────────────────────────────────
@app.get(f"{API}/sessions")
def sessions(days: int = 90, exercise_id: str = "", template_id: str = "", limit: int = 100, before: str = ""):
    return {"items": hercules.history(days=days, exercise_id=exercise_id, template_id=template_id, limit=limit,
                                      before=before or None)}


@app.get(f"{API}/sessions/active")
def session_active():
    act = hercules.active_session()
    return {"session": hercules.session_detail(act["id"]) if act else None}


@app.post(f"{API}/sessions")
def session_start(body: dict = Body(default={})):
    return hercules.start_session(body.get("template_id"), name=body.get("name") or "",
                                  started_at=body.get("started_at"), plan=body.get("exercises"))


@app.post(f"{API}/sessions/start-next")
def session_start_next(body: dict = Body(default={})):
    nxt = hercules.next_workout()
    act = hercules.active_session()
    if act:
        return {"session_id": act["id"], "resumed": True, "label": f"Ripreso {act.get('name')}"}
    sess = hercules.start_session((nxt.get("template") or {}).get("id"))
    return {"session_id": sess["id"], "label": f"Iniziato {sess.get('name')}"}


@app.post(f"{API}/sessions/log-text")
def session_log_text(body: dict = Body(...)):
    return hercules.log_sets_text(body.get("session_id"), str(body.get("text") or ""))


@app.get(f"{API}/sessions/{{id}}")
def session_get(id: str):
    return hercules.session_detail(id)


@app.patch(f"{API}/sessions/{{id}}")
def session_patch(id: str, body: dict = Body(...)):
    return hercules.update_session(id, body)


@app.delete(f"{API}/sessions/{{id}}")
def session_delete(id: str):
    out = hercules.delete("session", id)
    signals.changed()
    return out


@app.post(f"{API}/sessions/{{id}}/finish")
def session_finish(id: str, body: dict = Body(default={})):
    out = hercules.finish_session(id, notes=body.get("notes"), perceived_effort=body.get("perceived_effort"),
                                  ended_at=body.get("ended_at"), update_template=bool(body.get("update_template")))
    signals.changed()
    _sync_history()
    return out


def _sync_history() -> None:
    """Finished gym sessions → «Allenamenti» calendar (history), off the request thread."""
    def run():
        try:
            activities.sync_sessions(3)
        except Exception as exc:
            logger.warning("[🔄] event=hercules_history_sync_failed error=%s fallback=next_finish", exc)
    threading.Thread(target=run, daemon=True, name="hercules-history-sync").start()


@app.post(f"{API}/sessions/{{id}}/discard")
def session_discard(id: str):
    return hercules.discard_session(id)


@app.post(f"{API}/sessions/{{id}}/exercises")
def session_add_exercise(id: str, body: dict = Body(...)):
    return hercules.add_exercise(id, str(body.get("exercise_id") or ""), replace=body.get("replace"),
                                 sets=int(body.get("sets") or 3))


@app.post(f"{API}/sessions/{{id}}/sets")
def session_log_set(id: str, body: dict = Body(...)):
    return hercules.log_set(id, body)


@app.delete(f"{API}/sets/{{id}}")
def set_delete(id: str):
    out = hercules.delete("set", id)
    signals.changed()
    return out


# ── days, how I feel, adaptation ─────────────────────────────────────────────
@app.get(f"{API}/plans")
def plans(days: int = 21):
    return {"items": hercules.plans(days=days)}


@app.post(f"{API}/days/skip")
def day_skip(body: dict = Body(default={})):
    hercules.skip_day(body.get("date"), body.get("note") or "")
    return {"label": "Oggi saltato", "date": body.get("date") or hercules.today().isoformat()}


@app.delete(f"{API}/days/skip")
def day_unskip(date: str = ""):
    return hercules.unskip_day(date or None)


@app.post(f"{API}/days/postpone")
def day_postpone(body: dict = Body(...)):
    return hercules.postpone(str(body.get("to") or ""), body.get("from"), body.get("template_id"))


@app.post(f"{API}/checkin")
def checkin(body: dict = Body(...)):
    out = hercules.checkin(body)
    signals.changed()
    return out


@app.post(f"{API}/feedback")
def feedback(body: dict = Body(...)):
    return hercules.feedback(body)


@app.post(f"{API}/adapt")
def adapt_today(body: dict = Body(default={})):
    return hercules.adapt_today(body.get("readiness") or {k: body.get(k) for k in (
        "energy", "sleep", "soreness", "stress", "pain_areas", "time_minutes", "free_text") if body.get(k) is not None},
        intent=body.get("intent") or "", equipment_missing=body.get("equipment_missing"),
        template_id=body.get("template_id"))


@app.post(f"{API}/adapt/{{id}}/apply")
def adapt_apply(id: str):
    return hercules.apply_adaptation(id)


@app.post(f"{API}/restore")
def adapt_restore(body: dict = Body(default={})):
    return hercules.restore_today(body.get("session_id"))


# ── body, stats, goals ───────────────────────────────────────────────────────
@app.get(f"{API}/measurements")
def measurements(kind: str = "", days: int = 365):
    return {"items": hercules.measurements(kind, days)}


@app.post(f"{API}/measurements")
def measurement_add(body: dict = Body(...)):
    return hercules.save("measurement", {**body, "taken_at": body.get("taken_at") or now_iso()})


@app.delete(f"{API}/measurements/{{id}}")
def measurement_delete(id: str):
    return hercules.delete("measurement", id)


@app.get(f"{API}/stats")
def stats(per: str = "week", count: int = 12):
    return hercules.stats(per if per in domain.PERIODS else "week", count)


@app.get(f"{API}/records")
def records_list(exercise_id: str = "", days: int = 30):
    from .core import records as rec
    data = hercules.data()
    if exercise_id:
        return rec.exercise_records(data, exercise_id, hercules.formula())
    return {"items": rec.recent_prs(data, days, hercules.formula(), limit=50)}


@app.get(f"{API}/goals")
def goals():
    return {"items": hercules.goals()}


@app.post(f"{API}/goals")
def goal_save(body: dict = Body(...)):
    return hercules.save("goal", body, id=body.get("id"))


@app.delete(f"{API}/goals/{{id}}")
def goal_delete(id: str):
    return hercules.delete("goal", id)


def _summary_with_plan() -> dict:
    s = hercules.summary()
    planned = coach.next_planned()
    if planned:
        s["planned"] = planned
        s["text"] = f"{s['text']} · Nel piano: {planned['label']}"
    return s


@app.get(f"{API}/summary")
def summary():
    return {**_summary_with_plan(), "activities": _activity_hints()}


def _activity_hints() -> list[dict]:
    """«Corsa 1/2» for every open outdoor intention of this week (summary, widget, context)."""
    try:
        return [{"kind": i["kind"], "label": i["label"], "done": i["done"], "times": i["times"], "hint": i["hint"]}
                for i in activities.week()["intentions"]]
    except Exception as exc:
        logger.warning("[🔄] event=hercules_activity_hints_failed error=%s", exc)
        return []


def _recap_piece(day, nxt) -> dict:
    """Daily recap piece (docs/work/2026-10-20-recap-giornaliero)."""
    facts = hercules.recap(day, nxt)
    try:
        outdoor = activities.recap(day, nxt)
        for k in ("done", "missed", "next"):
            facts[k] = [*facts.get(k, []), *outdoor[k]]
    except Exception as exc:
        logger.warning("[🔄] event=hercules_activity_recap_failed error=%s fallback=gym_only", exc)
    return recap.piece("hercules", "Allenamento", icon="dumbbell", emoji="🏋️", order=30, **facts)


app.include_router(recap.recap_router("hercules", _recap_piece, today=lambda: hercules.today()))


@app.get("/api/module/context")
def module_context(budget: int = 400, topic: str = ""):
    """Shared contract (SPEC §9): a short caveman line the assistant may include. ``topic`` = a signal key
    (``stall:<exercise>``, ``missed_streak``…): the facts behind that signal; unknown topic → the normal line."""
    detail = hercules.signal_detail(topic) if topic else None
    if detail:
        if len(detail) > budget:
            detail = detail[: max(40, budget - 1)].rsplit("; ", 1)[0] + "…"
        return {"module": "hercules", "domain": "fitness", "updated_at": now_iso(), "text": detail}
    text = "Allenamento: " + _summary_with_plan()["text"]
    hints = [a["hint"] for a in _activity_hints()]
    if hints:
        text += " · All'aperto: " + ", ".join(hints)
    if len(text) > budget:
        text = text[: max(40, budget - 1)].rsplit(" · ", 1)[0] + "…"
    return {"module": "hercules", "domain": "fitness", "updated_at": now_iso(), "text": text}


# ── quick actions (WebUI Home) ───────────────────────────────────────────────
@app.get(f"{API}/quick/templates")
def quick_templates():
    return hercules.quick_chips()


@app.post(f"{API}/quick/{{id}}")
def quick_done(id: str, body: dict = Body(default={})):
    if id.startswith("resume:"):        # chip of the live session: nothing to log, the WebUI opens the page
        act = hercules.active_session()
        return {"session_id": act["id"] if act else None, "resumed": bool(act),
                "label": f"Ripreso {act.get('name')}" if act else "Nessun allenamento in corso"}
    out = hercules.quick_done(id, day=body.get("date"))
    signals.changed()
    return {**out, "label": f"{out['name']} segnato fatto"}


@app.delete(f"{API}/quick/{{id}}")
def quick_undo(id: str, date: str = ""):
    """Undo of 'Segna fatto': removes the last quick session of that template (today or ``date``)."""
    from .core import records as rec
    day = date or hercules.today().isoformat()
    rows = [s for s in hercules.store.items("session") if s.get("template_id") == id and s.get("source") == "quick"
            and str(rec.local_date(s.get("started_at"), hercules.tz)) == day]
    if not rows:
        raise NotFound("niente da annullare")
    rows.sort(key=lambda s: s.get("started_at") or "")
    out = hercules.delete("session", rows[-1]["id"])
    signals.changed()
    return out


@app.post(f"{API}/quick-bodyweight")
def quick_bodyweight(body: dict = Body(...)):
    value = body.get("peso", body.get("weight"))
    taken = f"{body['date']}T08:00:00+00:00" if body.get("date") else None
    m = hercules.log_measurement("bodyweight", float(str(value).replace(",", ".")), taken)
    return {**m, "label": f"Peso {m['value']} kg"}


# ── import / export ──────────────────────────────────────────────────────────
@app.post(f"{API}/import/preview")
def import_preview(body: dict = Body(...)):
    return hercules.import_preview(str(body.get("text") or ""), body.get("unit") or "kg")


@app.post(f"{API}/import/commit")
def import_commit(body: dict = Body(...)):
    out = hercules.import_commit(str(body.get("text") or ""), body.get("mapping") or {}, body.get("unit") or "kg")
    signals.changed()
    return out


@app.get(f"{API}/export")
def export(format: str = "csv"):
    text, mime = hercules.export("json" if format == "json" else "csv")
    return {"filename": f"hercules-{hercules.today().isoformat()}.{'json' if format == 'json' else 'csv'}",
            "mime": mime, "text": text}


# ── reminder (agenda job; off by default) ────────────────────────────────────
@app.post(f"{API}/reminder/check")
def reminder_check():
    decision = hercules.reminder_decision()
    if not decision.get("send"):
        logger.info("event=hercules_reminder_skipped why=%s", decision.get("why"))
        return decision
    goal, nxt = decision["goal"], decision.get("next") or {}
    tpl = nxt.get("template") or {}
    planned = coach.next_planned()
    text = f"🏋️ Oggi: {tpl.get('name', 'allenamento')}"
    if planned and planned["label"].startswith("oggi"):
        text += f" alle {planned['label'].split()[-1]}"
    if nxt.get("estimated_minutes"):
        text += f" · {nxt['estimated_minutes']} min"
    text += f" · {goal['hint']}"
    actions = []
    if tpl:
        actions.append({"id": "done", "label": "Segna fatto", "text": "✅ Segna fatto", "style": "primary",
                        "service": "hercules", "method": "POST", "path": f"{API}/quick/{tpl['id']}", "body": {},
                        "resolves": True})
    actions.append({"id": "skip", "label": "Salta oggi", "text": "⏭ Salta oggi", "service": "hercules",
                    "method": "POST", "path": f"{API}/days/skip", "body": {}})
    try:
        hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
            module="hercules", domain="fitness", key="hercules.reminder", title="Allenamento", text=text,
            actions=actions, page="allenamento", voice=bool(settings.get("hercules.notifiche.voce", True))),
            timeout=8)
        hercules.mark_reminder_sent()
        logger.info("event=hercules_reminder_sent template=%s hint=%s", tpl.get("id"), goal["hint"])
    except Exception as exc:
        logger.warning("[🔄] event=hercules_reminder_emit_failed error=%s fallback=next_check", exc)
        return {"send": False, "why": "hermes_unreachable"}
    return {"send": True, "text": text}


# ── outdoor activities (dossier 2026-10-20-meteo-hecate §3.8) ─────────────────
def _notify(msg: dict, title: str) -> bool:
    try:
        hub.call("hermes", "POST", "api/events/ingest", body=reminder_event(
            module="hercules", domain="fitness", key=msg["key"], title=title, text=msg["text"],
            actions=msg["actions"], page="allenamento"), timeout=8)
        return True
    except Exception as exc:
        logger.warning("[🔄] event=hercules_activity_notify_failed key=%s error=%s fallback=none", msg.get("key"), exc)
        return False


@app.get(f"{API}/activities")
def activities_week():
    return activities.week()


@app.post(f"{API}/activities/propose")
def activities_propose(body: dict = Body(default={})):
    return activities.propose(body.get("kind") or "corsa", int(body.get("times") or 1), str(body.get("place") or ""),
                              int(body.get("minutes") or 45), str(body.get("week") or ""))


@app.post(f"{API}/activities/log")
def activities_log(body: dict = Body(default={})):
    return activities.log(body.get("kind") or "corsa", str(body.get("date") or ""), domain._num(body.get("minutes"), integer=True),
                          domain._num(body.get("km")), str(body.get("note") or ""))


@app.post(f"{API}/activities/quick-run")
def activities_quick_run(body: dict = Body(default={})):
    """Home quick action «Ho corso» (``km`` optional, ``date`` for another day)."""
    return activities.log("corsa", str(body.get("date") or ""), None, domain._num(body.get("km")))


@app.delete(f"{API}/activities/quick-run")
def activities_quick_run_undo(date: str = ""):
    last = [a for a in activities.logs() if a.get("kind") == "corsa" and a.get("source") in ("log", "slot")
            and a["date"] == (date or hercules.today().isoformat())]
    if not last:
        return {"undone": False}
    return activities.unlog(last[-1]["id"])


@app.delete(f"{API}/activities/log/{{id}}")
def activities_unlog(id: str):
    return activities.unlog(id)


@app.post(f"{API}/activities/morning")
def activities_morning():
    """Agenda job (07:30): the coach line «Ottimo giorno per…» or «pioggia, spostiamo?», at most once a day."""
    msg = activities.morning()
    if not msg or msg.get("skip"):
        return {"send": False, "why": (msg or {}).get("skip") or "nothing_to_say"}
    if not _notify(msg, "Allenamento all'aperto"):
        return {"send": False, "why": "hermes_unreachable"}
    activities.mark_nudge()
    logger.info("event=hercules_activity_morning_sent key=%s", msg["key"])
    return {"send": True, "text": msg["text"]}


@app.post(f"{API}/activities/sync-calendar")
def activities_sync_calendar(body: dict = Body(default={})):
    return {"created": activities.sync_sessions(int(body.get("days") or 14))}


@app.post(f"{API}/activities/{{plan_id}}/confirm")
def activities_confirm(plan_id: str, body: dict = Body(default={})):
    slots = body.get("slots")
    return activities.confirm(plan_id, slots if isinstance(slots, list) and slots else None)


@app.post(f"{API}/activities/{{plan_id}}/slots")
def activities_add_slot(plan_id: str, body: dict = Body(default={})):
    return activities.add_slot(plan_id, str(body.get("start") or ""))


@app.post(f"{API}/activities/{{plan_id}}/keep")
def activities_keep(plan_id: str):
    """«Tengo» / «Non oggi» from the morning message: nothing changes."""
    return {"ok": True, "plan_id": plan_id}


@app.delete(f"{API}/activities/{{plan_id}}")
def activities_cancel(plan_id: str):
    return activities.cancel(plan_id)


@app.post(f"{API}/activities/{{plan_id}}/slots/{{slot_id}}/done")
def activities_slot_done(plan_id: str, slot_id: str, body: dict = Body(default={})):
    return activities.slot_done(plan_id, slot_id, domain._num(body.get("minutes"), integer=True), domain._num(body.get("km")))


@app.post(f"{API}/activities/{{plan_id}}/slots/{{slot_id}}/missed")
def activities_slot_missed(plan_id: str, slot_id: str):
    return activities.slot_missed(plan_id, slot_id)


@app.post(f"{API}/activities/{{plan_id}}/slots/{{slot_id}}/moved")
def activities_slot_moved(plan_id: str, slot_id: str, body: dict = Body(default={})):
    return activities.slot_moved(plan_id, slot_id, str(body.get("to") or ""))


@app.post(f"{API}/activities/{{plan_id}}/slots/{{slot_id}}/ask")
def activities_slot_ask(plan_id: str, slot_id: str):
    """Agenda task after the slot: «Hai fatto la corsa delle 18:00?» (Fatto / Non fatto / Spostato)."""
    msg = activities.ask(plan_id, slot_id)
    if not msg:
        return {"send": False, "why": "already_answered"}
    return {"send": _notify(msg, "Allenamento all'aperto")}


# ── reflection signals (agenda job hercules.signals) ─────────────────────────
@app.post(f"{API}/signals/run")
def signals_run():
    """Agenda job ``hercules.signals``: re-evaluate the training signals and weekly metrics, sync to Archive."""
    return signals.run()


def _agenda_rules() -> list[dict]:
    return [signals_rule("hercules", "Allenamento", path=f"{API}/signals/run", tz=TZ),
            job_rule("hercules.reminder", "Promemoria allenamento (Hercules)", service="hercules",
                     path=f"{API}/reminder/check", recurrence="FREQ=DAILY", start_at="2026-01-01T18:30:00",
                     description="Controlla se sei indietro con l'obiettivo di allenamento. Non invia nulla se il "
                                 "promemoria è spento nelle impostazioni (default) o se oggi ti sei già allenato.",
                     tz=TZ),
            job_rule("hercules.activity_morning", "Coach attività all'aperto (Hercules)", service="hercules",
                     path=f"{API}/activities/morning", recurrence="FREQ=DAILY", start_at="2026-01-01T07:30:00",
                     description="Solo mentre hai un'intenzione aperta (es. correre 2 volte questa settimana): "
                                 "«Ottimo giorno per…» quando il meteo è buono, o propone di spostare se piove.",
                     tz=TZ)]


# ── plugin (UI bundle) ───────────────────────────────────────────────────────
ui = PluginClient("hercules", title="Allenamento", icon="dumbbell", color="red",
                  description="Schede, allenamento live anche offline, record e progressi.", dist=UI_DIST,
                  version=SERVICE_VERSION)
ui.webui(
    entry="hercules.js", api_prefix=f"{API}/",
    pages=[page("allenamento", "Allenamento", element="hercules-today", icon="dumbbell", order=30,
                help="L'allenamento di oggi: check-in, inizia, registra serie con il timer."),
           page("schede", "Schede", element="hercules-templates", icon="list", order=31, parent="allenamento"),
           page("schede/:id", "Scheda", element="hercules-template", detail=True, parent="allenamento"),
           page("esercizi", "Esercizi", element="hercules-exercises", icon="search", order=32, parent="allenamento"),
           page("esercizi/:id", "Esercizio", element="hercules-exercise", detail=True, parent="allenamento"),
           page("storico", "Storico", element="hercules-history", icon="history", order=33, parent="allenamento"),
           page("storico/:id", "Allenamento", element="hercules-session", detail=True, parent="allenamento"),
           page("progressi", "Progressi", element="hercules-progress", icon="chart", order=34, parent="allenamento"),
           page("corpo", "Corpo", element="hercules-body", icon="scale", order=35, parent="allenamento")],
    widgets=[widget("prossimo", "Prossimo allenamento", element="hercules-next-widget", sizes=["m", "l"], auto=True,
                    open_page="allenamento", icon="dumbbell"),
             widget("settimana", "Settimana di allenamento", element="hercules-week-widget", sizes=["s", "m", "l"],
                    auto=True, open_page="progressi", icon="calendar"),
             widget("fatto", "Fatto oggi", element="hercules-quick-widget", sizes=["m", "l"], open_page="schede",
                    icon="check"),
             widget("record", "Record recenti", element="hercules-prs-widget", sizes=["m", "l"], open_page="progressi",
                    icon="trophy"),
             widget("esercizio", "Progresso esercizio", element="hercules-exercise-widget", sizes=["m", "l", "xl"],
                    params={"exercise": {"type": "string", "label": "Esercizio (nome)"}}, open_page="esercizi",
                    icon="chart"),
             widget("muscoli", "Volume per muscolo", element="hercules-volume-widget", sizes=["m", "l"],
                    params={"weeks": {"type": "int", "label": "Settimane", "default": 4}}, open_page="progressi",
                    icon="chart"),
             widget("peso", "Peso corporeo", element="hercules-weight-widget", sizes=["s", "m", "l"], open_page="corpo",
                    icon="scale"),
             widget("live", "Allenamento in corso", element="hercules-live-widget", sizes=["m", "l"],
                    open_page="allenamento", icon="timer")],
    quick_actions=[
        quick_action("fatto", "Segna fatto", "POST", f"{API}/quick/{{id}}", icon="check", group="Allenamento",
                     source=f"{API}/quick/templates", undo={"method": "DELETE", "path": f"{API}/quick/{{id}}"},
                     favorite=True, order=30),
        quick_action("inizia", "Inizia allenamento di oggi", "POST", f"{API}/sessions/start-next", icon="play",
                     group="Allenamento", order=31),
        quick_action("peso", "Registra peso corporeo", "POST", f"{API}/quick-bodyweight", icon="scale",
                     group="Allenamento", params={"peso": {"type": "float", "label": "Peso (kg)"}}, order=32),
        quick_action("corsa", "Ho corso", "POST", f"{API}/activities/quick-run", icon="run", group="Allenamento",
                     params={"km": {"type": "float", "label": "Km (facoltativo)"}},
                     undo={"method": "DELETE", "path": f"{API}/activities/quick-run"}, order=34),
        quick_action("salta", "Salta oggi", "POST", f"{API}/days/skip", icon="skip", group="Allenamento",
                     undo={"method": "DELETE", "path": f"{API}/days/skip"}, order=33),
    ],
)
app.include_router(ui.router())
app.include_router(settings.router())

# ── export / import (hestia_common.transfer; reminder and adaptation rows are runtime state) ────────────────
transfer = Transfer("hercules", hub, sections=[
    StoreSection("esercizi", "Esercizi", store, ["exercise"], icon="dumbbell"),
    StoreSection("schede", "Schede e programmi", store, ["template", "program"], icon="list",
                 depends_on=["esercizi"]),
    StoreSection("sessioni", "Sessioni", store, ["session", "set"], item_kinds=["session"], icon="history",
                 title=lambda r: r["data"].get("name") or "Sessione",
                 subtitle=lambda r: str(r["data"].get("started_at") or r.get("at") or "")[:10],
                 depends_on=["esercizi", "schede"]),
    StoreSection("misure", "Misure", store, ["measurement"], icon="scale",
                 title=lambda r: f"{r['data'].get('kind')}: {r['data'].get('value')} {r['data'].get('unit') or ''}"),
    StoreSection("obiettivi", "Obiettivi e piani", store, ["goal", "plan"], icon="target",
                 title=lambda r: r["data"].get("label") or r["data"].get("note") or r["data"].get("date") or r["id"],
                 depends_on=["esercizi", "schede"]),
    StoreSection("feedback", "Check-in e note", store, ["checkin", "feedback"], icon="note",
                 title=lambda r: r["data"].get("text") or r["data"].get("free_text") or "Check-in",
                 depends_on=["esercizi", "sessioni"]),
])
app.include_router(transfer.router())


# ── MCP tools (domain fitness; Oracle calls them, the logic stays here) ─────
def _t(fn):
    def run(**kw):
        try:
            return fn(**{k: v for k, v in kw.items() if v is not None})
        except (domain.Invalid, NotFound, Conflict) as exc:
            return {"error": str(exc), **(getattr(exc, "detail", {}) or {})}
    return run


try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router, mount_missing_rest_routes

    def _summary() -> dict:
        s = _summary_with_plan()
        return {"text": s["text"], "planned": s.get("planned"), "goals": s["goals"], "flags": s["flags"], "stalls": s["stalls"],
                "recent_prs": s["recent_prs"], "missed_7d": s["missed_7d"], "active_session": s["active_session"]}

    def _next() -> dict:
        n = hercules.next_workout()
        t = n.get("template")
        if t:
            detail = hercules.template_detail(t["id"])
            n["plan"] = [{"exercise": i["exercise"].get("name"), "sets": len(i.get("sets") or []),
                          "target": [(s.get("weight_kg"), s.get("reps")) for s in i["suggestion"]["sets"]],
                          "why": i["suggestion"]["reason"]} for i in detail["items"]]
            n["template"] = {"id": t["id"], "name": t["name"]}
        return n

    def _history(days: int = 30, exercise: str = "", limit: int = 20) -> dict:
        ex_id = ""
        if exercise:
            ex = hercules._find_exercise(exercise, hercules.store.items("exercise"))
            ex_id = ex["id"] if ex else ""
        return {"sessions": hercules.history(days=days, exercise_id=ex_id, limit=limit)}

    def _exercise_stats(exercise: str = "") -> dict:
        ex = hercules._find_exercise(exercise, hercules.store.items("exercise"))
        if not ex:
            return {"error": f"esercizio '{exercise}' non trovato"}
        d = hercules.exercise_detail(ex["id"])
        return {"exercise": ex["name"], "records": d["records"], "stall": d["stall"],
                "last_sessions": [{k: h[k] for k in ("date", "top_weight", "top_reps", "best_e1rm", "sets", "volume")}
                                  for h in d["history"][:8]]}

    def _search(query: str = "", muscle: str = "") -> dict:
        return {"items": [{"id": e["id"], "name": e["name"], "equipment": e["equipment"],
                           "muscles": e["primary_muscles"]} for e in hercules.exercises(query, muscle)[:15]]}

    def _templates() -> dict:
        return {"items": [{"id": t["id"], "name": t["name"], "exercises": t["exercise_names"],
                           "minutes": t["estimated_minutes"], "last_done": t["last_done"]} for t in hercules.templates()]}

    def _start(template: str = "") -> dict:
        tid = None
        if template:
            match = [t for t in hercules.templates() if template.lower() in t["name"].lower() or t["id"] == template]
            if not match:
                return {"error": f"scheda '{template}' non trovata"}
            tid = match[0]["id"]
        else:
            tid = (hercules.next_workout().get("template") or {}).get("id")
        s = hercules.start_session(tid)
        return {"session_id": s["id"], "name": s["name"], "exercises": [b["exercise"].get("name") for b in s["blocks"]]}

    def _log(text: str = "") -> dict:
        r = hercules.log_sets_text(None, text)
        return {"logged": r["logged"], "unknown": r["unknown"], "session_id": r["session_id"]}

    def _finish(notes: str = "", effort: int | None = None) -> dict:
        act = hercules.active_session()
        if not act:
            return {"error": "nessun allenamento in corso"}
        d = hercules.finish_session(act["id"], notes=notes or None, perceived_effort=effort)
        signals.changed()
        return {"summary": d.get("summary"), "prs": d.get("prs")}

    def _checkin(energy: int | None = None, sleep: int | None = None, soreness: list | None = None,
                 pain_areas: list | None = None, time_minutes: int | None = None, free_text: str = "") -> dict:
        row = hercules.checkin({"energy": energy, "sleep": sleep, "soreness": soreness or [], "pain_areas": pain_areas or [],
                                "time_minutes": time_minutes, "free_text": free_text})
        signals.changed()
        return {"saved": True, "checkin": row}

    def _adapt(energy: int | None = None, time_minutes: int | None = None, pain_areas: list | None = None,
               soreness: list | None = None, equipment_missing: list | None = None, intent: str = "",
               free_text: str = "") -> dict:
        readiness = {k: v for k, v in {"energy": energy, "time_minutes": time_minutes, "pain_areas": pain_areas,
                                       "soreness": soreness, "free_text": free_text}.items() if v}
        r = hercules.adapt_today(readiness, intent=intent, equipment_missing=equipment_missing)
        return {k: r[k] for k in ("adaptation_id", "name", "trace", "warnings", "minutes_before", "minutes_after",
                                  "plan_text")}

    def _apply(adaptation_id: str = "") -> dict:
        d = hercules.apply_adaptation(adaptation_id)
        return {"session_id": d["id"], "name": d["name"], "exercises": [b["exercise"].get("name") for b in d["blocks"]]}

    def _restore() -> dict:
        d = hercules.restore_today()
        return {"session_id": d["id"], "exercises": [b["exercise"].get("name") for b in d["blocks"]]}

    def _skip(date: str = "", note: str = "") -> dict:
        return hercules.skip_day(date or None, note)

    def _postpone(to: str = "", date_from: str = "") -> dict:
        return hercules.postpone(to, date_from or None)

    def _feedback(text: str = "", tags: list | None = None, exercise: str = "") -> dict:
        ex = hercules._find_exercise(exercise, hercules.store.items("exercise")) if exercise else None
        act = hercules.active_session()
        last = (hercules.data().sessions or [None])[-1]
        sid = (act or last or {}).get("id")
        return hercules.feedback({"text": text, "tags": tags or [], "exercise_id": ex["id"] if ex else None,
                                  "session_id": sid, "source": "assistant"})

    def _edit_template(template: str = "", changes: dict | None = None, remove_exercise: str = "",
                       add_exercise: str = "", sets: int | None = None, reps_min: int | None = None,
                       reps_max: int | None = None) -> dict:
        match = [t for t in hercules.store.items("template") if template.lower() in t["name"].lower() or t["id"] == template]
        if not match:
            return {"error": f"scheda '{template}' non trovata"}
        t = dict(match[0])
        exs = hercules.store.items("exercise")
        items = list(t.get("items") or [])
        if remove_exercise:
            ex = hercules._find_exercise(remove_exercise, exs)
            items = [i for i in items if not ex or i["exercise_id"] != ex["id"]]
        if add_exercise:
            ex = hercules._find_exercise(add_exercise, exs)
            if not ex:
                return {"error": f"esercizio '{add_exercise}' non trovato"}
            n = sets or 3
            items.append({"exercise_id": ex["id"], "sets": [{"reps_min": reps_min or 8, "reps_max": reps_max or 12}
                                                            for _ in range(n)]})
        t["items"] = items
        if changes:
            t.update({k: v for k, v in changes.items() if k in ("name", "notes", "folder", "favorite")})
        saved = hercules.save_template(t, by_assistant=True)
        return {"saved": True, "template": saved["name"], "revision": saved.get("revision"),
                "exercises": [next((e["name"] for e in exs if e["id"] == i["exercise_id"]), "?") for i in saved["items"]],
                "undo": "fitness_undo_template"}

    def _undo_template(template: str = "") -> dict:
        match = [t for t in hercules.store.items("template") if template.lower() in t["name"].lower() or t["id"] == template]
        if not match:
            return {"error": f"scheda '{template}' non trovata"}
        return {"restored": hercules.undo_template(match[0]["id"])["name"]}

    def _measure(value: float = 0, kind: str = "bodyweight") -> dict:
        return hercules.log_measurement(kind, value)

    def _goal(times: int = 3, per: str = "week", scope: str = "any", target: str = "", active: bool = True) -> dict:
        target_id = None
        if scope == "template":
            match = [t for t in hercules.store.items("template") if target.lower() in t["name"].lower()]
            target_id = match[0]["id"] if match else None
        elif scope == "muscle":
            target_id = target.lower()
        existing = next((g for g in hercules.store.items("goal") if g.get("scope") == scope and g.get("target_id") == target_id), None)
        return hercules.save("goal", {"times": times, "per": per, "scope": scope, "target_id": target_id, "active": active},
                             id=existing["id"] if existing else None)

    def _plan_activity(kind: str = "corsa", times: int = 1, place: str = "", minutes: int = 45, week: str = "") -> dict:
        return activities.propose(kind, times, place, minutes, week)

    def _confirm_activity(plan_id: str = "", slots: list | None = None) -> dict:
        return activities.confirm(plan_id, slots or None)

    def _log_activity(kind: str = "corsa", date: str = "", minutes: int | None = None, km: float | None = None,
                      note: str = "") -> dict:
        return activities.log(kind, date, minutes, km, note)

    def _activities_week() -> dict:
        return activities.week()

    def _activity_outcome(plan_id: str = "", slot_id: str = "", outcome: str = "done", to: str = "") -> dict:
        if outcome == "missed":
            return activities.slot_missed(plan_id, slot_id)
        if outcome == "moved":
            return activities.slot_moved(plan_id, slot_id, to)
        return activities.slot_done(plan_id, slot_id)

    def _cancel_activity(plan_id: str = "") -> dict:
        return activities.cancel(plan_id)

    S = {"type": "string"}
    I = {"type": "integer"}
    L = {"type": "array", "items": {"type": "string"}}
    _tools = [
        MCPTool(name="fitness_summary", description="Allenamento a colpo d'occhio: prossimo allenamento, obiettivo "
                "(es. 2/3 settimana), record recenti, stalli, giorni saltati, segnali di energia bassa. Usalo per "
                "qualsiasi domanda su palestra/allenamento prima di altro.", parameters={"type": "object", "properties": {}},
                handler=_t(_summary), title="Riepilogo allenamento", path=f"{API}/summary", clients=["telegram", "ui"],
                telegram_group="allenamento",
                telegram={"section": "Oggi", "summary": True}),
        MCPTool(name="fitness_next_workout", description="Il prossimo allenamento con esercizi e pesi suggeriti "
                "(progressione automatica) e il motivo.", parameters={"type": "object", "properties": {}},
                handler=_t(_next), title="Allenamento di oggi", path=f"{API}/next", clients=["telegram", "ui"],
                telegram_group="allenamento",
                telegram={"section": "Oggi", "primary": 2}),
        MCPTool(name="fitness_history", description="Allenamenti passati (giorni indietro, filtro esercizio).",
                parameters={"type": "object", "properties": {"days": I, "exercise": S, "limit": I}},
                handler=_t(_history), title="Storico allenamenti", path=f"{API}/sessions", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Storico e statistiche", "label": "Storico"}),
        MCPTool(name="fitness_exercise_stats", description="Record e andamento di un esercizio (massimale stimato, "
                "peso massimo, ultime sedute, stallo).", parameters={"type": "object", "properties": {"exercise": S},
                                                                       "required": ["exercise"]},
                handler=_t(_exercise_stats), title="Statistiche esercizio", path=f"{API}/records", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Storico e statistiche"}),
        MCPTool(name="fitness_search_exercises", description="Cerca esercizi nel catalogo (nome o muscolo: petto, "
                "spalle, braccia, schiena, core, gambe).", parameters={"type": "object", "properties": {"query": S, "muscle": S}},
                handler=_t(_search), title="Cerca esercizi", path=f"{API}/exercises", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Schede"}),
        MCPTool(name="fitness_templates", description="Le mie schede di allenamento con esercizi e durata.",
                parameters={"type": "object", "properties": {}}, handler=_t(_templates), title="Schede",
                path=f"{API}/templates", clients=["telegram", "ui"], telegram_group="allenamento",
                telegram={"section": "Schede", "primary": 5}),
        MCPTool(name="fitness_start_session", description="Inizia un allenamento (scheda per nome, vuoto = quella di oggi).",
                parameters={"type": "object", "properties": {"template": S}}, handler=_t(_start),
                title="Inizia allenamento", method="POST", path=f"{API}/sessions", clients=["telegram", "ui"],
                telegram_group="allenamento",
                telegram={"section": "Oggi", "primary": 1}),
        MCPTool(name="fitness_log_sets", description="Registra serie nell'allenamento in corso dal testo: "
                "'panca 80x8, 80x8, 77.5x7; trazioni 8, 7, 6'. Peso x ripetizioni (x serie), @RPE opzionale.",
                parameters={"type": "object", "properties": {"text": S}, "required": ["text"]}, handler=_t(_log),
                title="Registra serie", method="POST", path=f"{API}/sessions/log-text", clients=["telegram", "ui"],
                telegram_group="allenamento",
                telegram={"section": "Oggi"}),
        MCPTool(name="fitness_finish_session", description="Concludi l'allenamento in corso: riepilogo e nuovi record.",
                parameters={"type": "object", "properties": {"notes": S, "effort": I}}, handler=_t(_finish),
                title="Fine allenamento", method="POST", path=f"{API}/sessions/{{id}}/finish",
                clients=["telegram", "ui"], telegram_group="allenamento",
                telegram={"section": "Oggi"}),
        MCPTool(name="fitness_checkin", description="Salva come mi sento oggi: energia 1-5, sonno 1-5, indolenzimenti, "
                "dolori (spalla, ginocchio, schiena…), minuti a disposizione.",
                parameters={"type": "object", "properties": {"energy": I, "sleep": I, "soreness": L, "pain_areas": L,
                                                             "time_minutes": I, "free_text": S}},
                handler=_t(_checkin), title="Come stai oggi", method="POST", path=f"{API}/checkin", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Oggi", "label": "Check-in"}),
        MCPTool(name="fitness_adapt_today", description="Proponi l'allenamento di oggi adattato a come sto (energia "
                "1-5, minuti, dolori, indolenzimenti, attrezzi mancanti, intent lighter|shorter|harder). NON lo applica: "
                "mostra all'utente 'trace' e chiedi se va bene; se dice sì chiama fitness_apply_adaptation. "
                "Mai consigliare di allenarsi sul dolore.",
                parameters={"type": "object", "properties": {"energy": I, "time_minutes": I, "pain_areas": L,
                                                             "soreness": L, "equipment_missing": L, "intent": S,
                                                             "free_text": S}},
                handler=_t(_adapt), title="Adatta allenamento", method="POST", path=f"{API}/adapt", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Oggi"}),
        MCPTool(name="fitness_apply_adaptation", description="Applica l'adattamento proposto (solo dopo il sì dell'utente).",
                parameters={"type": "object", "properties": {"adaptation_id": S}, "required": ["adaptation_id"]},
                handler=_t(_apply), title="Applica adattamento", method="POST", path=f"{API}/adapt/{{adaptation_id}}/apply",
                clients=["ui"], telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Oggi"}),
        MCPTool(name="fitness_restore_today", description="Ripristina la scheda originale di oggi (annulla l'adattamento).",
                parameters={"type": "object", "properties": {}}, handler=_t(_restore), title="Ripristina scheda di oggi",
                method="POST", path=f"{API}/restore", clients=["ui"], telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Oggi"}),
        MCPTool(name="fitness_skip_day", description="Segna saltato l'allenamento di un giorno (default oggi).",
                parameters={"type": "object", "properties": {"date": S, "note": S}}, handler=_t(_skip),
                title="Salta allenamento", method="POST", path=f"{API}/days/skip", clients=["telegram", "ui"],
                telegram_group="allenamento",
                telegram={"section": "Oggi", "primary": 6, "label": "Salta oggi"}),
        MCPTool(name="fitness_postpone", description="Sposta l'allenamento di oggi (o di date_from) al giorno 'to' (YYYY-MM-DD).",
                parameters={"type": "object", "properties": {"to": S, "date_from": S}, "required": ["to"]},
                handler=_t(_postpone), title="Sposta allenamento", method="POST", path=f"{API}/days/postpone",
                clients=["ui"], telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Oggi"}),
        MCPTool(name="fitness_feedback", description="Salva un feedback sull'allenamento o su un esercizio. tags: "
                "too_heavy, too_light, pain, great, tired, bored, short_time, technique. Le regole lo usano la volta dopo.",
                parameters={"type": "object", "properties": {"text": S, "tags": L, "exercise": S}}, handler=_t(_feedback),
                title="Com'è andato l'allenamento", method="POST", path=f"{API}/feedback", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Oggi", "label": "Feedback"}),
        MCPTool(name="fitness_edit_template", description="Modifica una scheda: togli/aggiungi esercizio, serie e "
                "ripetizioni. Solo dopo che l'utente ha detto sì in chat. Annullabile con fitness_undo_template.",
                parameters={"type": "object", "properties": {"template": S, "remove_exercise": S, "add_exercise": S,
                                                             "sets": I, "reps_min": I, "reps_max": I,
                                                             "changes": {"type": "object"}}, "required": ["template"]},
                handler=_t(_edit_template), title="Modifica scheda", method="PUT", path=f"{API}/templates/{{id}}",
                clients=["ui"], telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Schede"}),
        MCPTool(name="fitness_undo_template", description="Annulla l'ultima modifica di una scheda.",
                parameters={"type": "object", "properties": {"template": S}, "required": ["template"]},
                handler=_t(_undo_template), title="Annulla modifica scheda", method="POST",
                path=f"{API}/templates/{{id}}/undo", clients=["ui"], telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Schede"}),
        MCPTool(name="fitness_log_measurement", description="Registra peso corporeo (kg) o una misura (kind: waist, "
                "chest, arm, thigh, body_fat…).", parameters={"type": "object", "properties": {
                    "value": {"type": "number"}, "kind": S}, "required": ["value"]},
                handler=_t(_measure), title="Registra peso", method="POST", path=f"{API}/measurements",
                clients=["telegram", "ui"], telegram_group="allenamento",
                telegram={"section": "Obiettivi e corpo", "primary": 3}),
        MCPTool(name="fitness_set_goal", description="Imposta un obiettivo di allenamento: times per day|week|month; "
                "scope any (qualsiasi), template (target = nome scheda) o muscle (petto, spalle, braccia, schiena, core, gambe).",
                parameters={"type": "object", "properties": {"times": I, "per": S, "scope": S, "target": S,
                                                             "active": {"type": "boolean"}}, "required": ["times"]},
                handler=_t(_goal), title="Obiettivo allenamento", method="POST", path=f"{API}/goals", clients=["ui"],
                telegram_visible=False, telegram_group="allenamento",
                telegram={"section": "Obiettivi e corpo"}),
        MCPTool(name="fitness_plan_activity", description="Intenzione di attività all'aperto («ho voglia di correre 2 "
                "volte questa settimana»): kind corsa|bici|camminata|nuoto|altro, times, place (nome di un luogo salvato "
                "o città; vuoto = Casa), minutes, week (vuoto = questa, 'next' = prossima). Propone i momenti migliori "
                "da meteo e impegni; NON scrive nel calendario: mostra i momenti e chiedi conferma.",
                parameters={"type": "object", "properties": {"kind": S, "times": I, "place": S, "minutes": I, "week": S}},
                handler=_t(_plan_activity), title="Pianifica attività", method="POST",
                path=f"{API}/activities/propose", clients=["telegram", "ui"], telegram_group="allenamento",
                telegram={"section": "Attività"}),
        MCPTool(name="fitness_confirm_activity", description="Conferma l'intenzione proposta (dopo il sì dell'utente): "
                "slots = numeri dei momenti da tenere o orari ISO scelti dall'utente (vuoto = tutti). Crea gli eventi "
                "nel calendario «Allenamenti» e dopo ogni uscita chiede se è stata fatta.",
                parameters={"type": "object", "properties": {"plan_id": S, "slots": L}, "required": ["plan_id"]},
                handler=_t(_confirm_activity), title="Conferma attività", method="POST",
                path=f"{API}/activities/{{plan_id}}/confirm", clients=["ui"], telegram_visible=False,
                telegram_group="allenamento",
                telegram={"section": "Attività"}),
        MCPTool(name="fitness_log_activity", description="Registra un'attività fatta («ho corso 5 km»): kind, date "
                "(vuoto = oggi), minutes, km, note. Chiude il momento pianificato di quel giorno se c'è.",
                parameters={"type": "object", "properties": {"kind": S, "date": S, "minutes": I,
                                                             "km": {"type": "number"}, "note": S}},
                handler=_t(_log_activity), title="Registra attività", method="POST", path=f"{API}/activities/log",
                clients=["telegram", "ui"], telegram_group="allenamento",
                telegram={"section": "Attività", "primary": 4}),
        MCPTool(name="fitness_activities", description="Attività all'aperto di questa settimana: intenzioni con "
                "progresso (es. Corsa 1/2), momenti pianificati e attività fatte.",
                parameters={"type": "object", "properties": {}}, handler=_t(_activities_week),
                title="Attività della settimana", path=f"{API}/activities", clients=["telegram", "ui"],
                telegram_group="allenamento",
                telegram={"section": "Attività"}),
        MCPTool(name="fitness_activity_outcome", description="Esito di un momento pianificato: outcome done|missed|"
                "moved (to = nuovo orario ISO; vuoto = il migliore rimasto nella settimana).",
                parameters={"type": "object", "properties": {"plan_id": S, "slot_id": S, "outcome": S, "to": S},
                            "required": ["plan_id", "slot_id"]},
                handler=_t(_activity_outcome), title="Esito attività", method="POST",
                path=f"{API}/activities/{{plan_id}}/slots/{{slot_id}}/done", clients=["ui"], telegram_visible=False,
                telegram_group="allenamento",
                telegram={"section": "Attività"}),
        MCPTool(name="fitness_cancel_activity", description="Annulla un'intenzione (toglie gli eventi futuri dal calendario).",
                parameters={"type": "object", "properties": {"plan_id": S}, "required": ["plan_id"]},
                handler=_t(_cancel_activity), title="Annulla attività", method="DELETE",
                path=f"{API}/activities/{{plan_id}}", clients=["ui"], telegram_visible=False,
                telegram_group="allenamento",
                telegram={"section": "Attività"}),
    ]
    def _coerced(t: MCPTool):
        """REST callers (Telegram, gateway) send strings: coerce by the tool's schema before the handler."""
        props = (t.parameters or {}).get("properties") or {}
        inner = t.handler

        def run(**kw):
            for k, v in list(kw.items()):
                typ = (props.get(k) or {}).get("type")
                if not isinstance(v, str):
                    continue
                if typ == "integer" and v.strip().lstrip("-").isdigit():
                    kw[k] = int(v)
                elif typ == "number":
                    try:
                        kw[k] = float(v.replace(",", "."))
                    except ValueError:
                        pass
                elif typ == "boolean":
                    kw[k] = v.lower() in ("1", "true", "si", "sì", "yes")
                elif typ == "array":
                    kw[k] = [x.strip() for x in v.split(",") if x.strip()]
            return inner(**{k: v for k, v in kw.items() if k in props})
        return run

    for _tool in _tools:
        # one REST path per tool whose arguments are exactly the tool's (served by mount_missing_rest_routes)
        _tool.path = f"{API}/tools/{_tool.name.removeprefix('hercules_')}"
        _tool.handler = _coerced(_tool)
    app.include_router(create_mcp_router(_tools, service_name="hercules"))
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=hercules reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_hercules"))
try:
    mount_missing_rest_routes(app, _tools, service_name="hercules")
except NameError:
    pass


# ── Hub registration ─────────────────────────────────────────────────────────
def _registration() -> dict:
    caps = {"mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": ["fitness"],
            "context_endpoint": "/api/module/context", **recap.capabilities()}
    try:
        caps.update(ui.capabilities(SERVICE_BASE_URL))
        caps.update(transfer.capabilities())
    except Exception as exc:
        logger.warning("[🔄] event=hercules_ui_manifest_failed error=%s fallback=no_ui", exc)
    return {"name": SERVICE_NAME, "base_url": SERVICE_BASE_URL, "health_endpoint": "/health",
            "service_type": SERVICE_TYPE, "service_version": SERVICE_VERSION, "tags": SERVICE_TAGS,
            "topology_tags": SERVICE_TOPOLOGY_TAGS, "capabilities": caps}


def _register() -> None:
    resp = requests.post(f"{HUB_API_URL}/registry/register", json=_registration(), timeout=4)
    if resp.status_code >= 400:
        logger.warning("event=hub_registration_non_success status=%s body=%s", resp.status_code, resp.text[:200])
    else:
        logger.info("event=registered_on_hub hub=%s base_url=%s", HUB_API_URL, SERVICE_BASE_URL)


def _warm_up() -> None:
    """Load the mirror and seed the catalog in the background (never block startup on Archive)."""
    import time
    for attempt in range(1, 1000):
        try:
            if store.refresh(force=True):
                hercules.ensure_catalog()
                signals.changed()           # time-based facts may have moved while the service was down
                return
        except Exception as exc:
            logger.warning("[🔄] event=hercules_warmup_failed attempt=%d error=%s", attempt, exc)
        time.sleep(min(60, 5 * attempt))


@app.on_event("startup")
def startup():
    try:
        _register()
    except Exception as exc:
        logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
    from hestia_common.startup_utils import start_hub_keepalive
    start_hub_keepalive(_register, logger=logger, name="hercules-hub-keepalive")
    settings.start()
    agenda.register_async(_agenda_rules)
    threading.Thread(target=_warm_up, daemon=True, name="hercules-warmup").start()

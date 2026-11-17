"""Hestia-Hygieia — self care: products, routines as goals, one-tap tracking, statistics (domain ``selfcare``).

SPEC docs/work/2026-10-17-selfcare-module. Data in Archive (``/api/selfcare-store``), settings in Themis, reminders
and alerts through the agenda (Chronos) and Hermes (one live reminder per routine), UI as a plugin bundle (``ui/``),
assistant tools over MCP.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import date as _date, timedelta
from pathlib import Path
from typing import Any

import requests
from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from hestia_common.i18n import is_yes, t as tr, weekday_of  # owner language; owner words per language

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common import recap
from hestia_common.display import action, display, item
from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.coach import CoachClient, CoachRouter
from hestia_common.plugin_client import PluginClient, page, quick_action, widget
from hestia_common.reminders import reminder_event, reminder_settings, voice_setting
from hestia_common.transfer import StoreSection, Transfer
from hestia_common.settings_client import SettingsClient, setting
from hestia_common.signals_client import Signals, signals_rule
from hestia_common.feeds import capabilities as feed_capabilities
from hestia_common.voice_client import VoiceClient
from hestia_common.voice_usecases import capabilities as voice_capabilities, usecase as voice_usecase

from .core import catalog
from .core.coach import HygieiaCoach
from .core.hub import Hub
from .core.planner import cadence_label
from .core.service import DIARY_VOICE_USE, Conflict, Hygieia, Invalid, NotFound
from .core.store import Store, StoreUnavailable, now_iso

logger, log_buffer = setup_service_logging("hestia_hygieia")

SERVICE_NAME = os.getenv("SERVICE_NAME", "hygieia")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_hygieia:19018")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "module")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "module,selfcare,context,coach").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:domain,domain:selfcare,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
UI_DIST = os.getenv("HYGIEIA_UI_DIST", "/code/ui/dist")
TZ = os.getenv("TZ") or "Europe/Rome"
API = "/api/selfcare"

# ── settings (Themis) ────────────────────────────────────────────────────────
settings = SettingsClient("hygieia")
settings.declare([
    setting("hygieia.default_pao_months", "Duration after opening", "int", 12, group="Products", min=1, max=60, unit="months",
            help="When the product does not show the PAO (the «12M» jar)."),
    *reminder_settings("hygieia", help="Then choose on each routine whether you want the reminder. At most N a week per routine; only one stays visible and says how many times you skipped it."),
    voice_setting("hygieia", True),
    setting("hygieia.alerts.enabled", "Product alerts", "bool", True, group="Notices",
            help="Deadlines and products running out, one per product."),
    setting("hygieia.alerts.expiry_days", "Deadline alert", "int", 30, group="Notices", min=1, max=180, unit="days",
            depends_on={"key": "hygieia.alerts.enabled", "equals": True}),
    setting("hygieia.alerts.restock_days", "Buy again alert", "int", 14, group="Notices", min=1, max=90, unit="days",
            help="When the estimate says it runs out within these days.",
            depends_on={"key": "hygieia.alerts.enabled", "equals": True}),
]).follow_personal()                                       # week start, currency: personal settings shared by every module

hub = Hub(HUB_API_URL)
store = Store(hub)
voice = VoiceClient(HUB_API_URL)
VOICE_USECASES = [voice_usecase(DIARY_VOICE_USE, "Spoken diary", direction="listen",
                                help="The story of the day after the evening recap.")]
hygieia = Hygieia(store, settings.get, tz_name=TZ)
coach = HygieiaCoach(hygieia)
coach_client = CoachClient("hygieia", HUB_API_URL)


def _coach_event(event: str, data: dict) -> None:
    """Tell the weekly plan (Chronos) in the background."""
    def _send():
        if event == "done":
            coach_client.done(data.get("need_id") or "routine", data.get("at"))
        elif event == "skipped":
            coach_client.skipped(data.get("need_id") or "routine", data.get("at"))
        else:
            coach_client.changed()
    threading.Thread(target=_send, daemon=True, name=f"hygieia-coach-{event}").start()


hygieia.on_event = _coach_event
agenda = AgendaClient("hygieia", HUB_API_URL)
# reflection signals (Archive signals-store): re-evaluated after the natural writes and by the daily agenda job
signals = Signals("hygieia", "selfcare", evaluate=hygieia.signals, hub_api_url=HUB_API_URL)

app = FastAPI(title="Hestia-Hygieia", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(CoachRouter("hygieia", "selfcare", "Self care", needs=coach.needs, review=coach.review).router)


@app.exception_handler(Invalid)
async def _invalid(_: Request, exc: Invalid):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(Conflict)
async def _conflict(_: Request, exc: Conflict):
    return JSONResponse(status_code=409, content={"detail": str(exc), **exc.detail})


@app.exception_handler(StoreUnavailable)
async def _store_down(_: Request, exc: StoreUnavailable):
    return JSONResponse(status_code=503, content={"detail": tr("archive not reachable, try again shortly")})


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hygieia", "version": SERVICE_VERSION, "mirror_loaded": store.loaded,
            "rows": len(store.rows), "cursor": store.cursor}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    logs = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_hygieia", "count": len(logs), "logs": logs}


# ── lists ────────────────────────────────────────────────────────────────────
@app.get(f"{API}/meta")
def meta():
    return hygieia.meta()


@app.post(f"{API}/options/{{name}}")
def option_add(name: str, body: dict = Body(...)):
    return hygieia.add_option(name, body)


@app.delete(f"{API}/options/{{id}}")
def option_delete(id: str):
    row = hygieia.get("option", id)
    hygieia.store.upsert("option", id, {**{k: v for k, v in row.items() if k != "id"}, "archived": True})
    return {"deleted": True, "id": id}


# ── products ─────────────────────────────────────────────────────────────────
@app.get(f"{API}/products")
def products(q: str = "", area: str = "", category: str = "", status: str = "", active: str = "", sort: str = "",
             limit: int = 500):
    items = hygieia.products(q, area, category, status, active, sort)
    return {"count": len(items), "items": items[: max(1, min(limit, 2000))]}


@app.post(f"{API}/products")
def product_create(body: dict = Body(...)):
    return hygieia.save_product(body, source=body.get("source") or "webui")


@app.get(f"{API}/products/{{id}}")
def product_get(id: str):
    return hygieia.product_detail(id)


@app.put(f"{API}/products/{{id}}")
def product_update(id: str, body: dict = Body(...)):
    hygieia.get("product", id)
    return hygieia.save_product(body, id=id, source=body.get("source") or "webui")


@app.delete(f"{API}/products/{{id}}")
def product_delete(id: str):
    return hygieia.delete_product(id)


@app.post(f"{API}/products/{{id}}/status")
def product_status(id: str, body: dict = Body(...)):
    out = hygieia.set_status(id, str(body.get("status") or ""), body.get("date"))
    return {**out, "label": f"{out['name']}: {out['status_label'].lower()}"}


@app.post(f"{API}/products/{{id}}/level")
def product_level(id: str, body: dict = Body(...)):
    return hygieia.save_product({"level": body.get("level")}, id=id)


@app.post(f"{API}/products/{{id}}/repurchase")
def product_repurchase(id: str, body: dict = Body(default={})):
    out = hygieia.repurchase(id, body)
    return {**out, "label": tr("{0} bought again", out['name'])}


@app.post(f"{API}/products/{{id}}/use")
def product_use(id: str, body: dict = Body(default={})):
    out = hygieia.log_product(id, body.get("date"), body.get("note") or "")
    return {**out, "label": tr("{0} used", out['name'])}


@app.delete(f"{API}/products/{{id}}/use")
def product_unuse(id: str, date: str = ""):
    return hygieia.undo_log(product_id=id, day=date or None)


# ── routines ─────────────────────────────────────────────────────────────────
@app.get(f"{API}/routines")
def routines(archived: bool = False):
    return {"items": hygieia.routines(include_archived=archived)}


@app.post(f"{API}/routines")
def routine_create(body: dict = Body(...)):
    return hygieia.save_routine(body, reason=body.get("reason") or "", source=body.get("source") or "webui")


@app.get(f"{API}/routines/{{id}}")
def routine_get(id: str):
    return hygieia.routine_detail(id)


@app.put(f"{API}/routines/{{id}}")
def routine_update(id: str, body: dict = Body(...)):
    return hygieia.save_routine(body, id=id, reason=body.get("reason") or "", source=body.get("source") or "webui")


@app.delete(f"{API}/routines/{{id}}")
def routine_delete(id: str):
    return hygieia.delete_routine(id)


@app.post(f"{API}/routines/{{id}}/undo")
def routine_undo(id: str):
    return hygieia.undo_routine(id)


@app.get(f"{API}/routines/{{id}}/plan")
def routine_plan(id: str, date: str = ""):
    return hygieia.routine_plan(id, date or None)


@app.post(f"{API}/routines/{{id}}/done")
def routine_done(id: str, body: dict = Body(default={})):
    out = hygieia.log_routine(id, body.get("date"), body.get("status") or "done", body.get("steps"), body.get("note") or "",
                              source=body.get("source") or "webui")
    signals.changed()
    return {**out, "label": tr("{0} done", out['name'])}


@app.delete(f"{API}/routines/{{id}}/done")
def routine_undone(id: str, date: str = ""):
    out = hygieia.undo_log(routine_id=id, day=date or None)
    signals.changed()
    return out


@app.post(f"{API}/routines/{{id}}/skip")
def routine_skip(id: str, body: dict = Body(default={})):
    out = hygieia.log_routine(id, body.get("date"), "skipped", None, body.get("note") or "", source=body.get("source") or "webui")
    signals.changed()
    return {**out, "label": tr("{0} skipped", out['name'])}


@app.post(f"{API}/routines/{{id}}/snooze")
def routine_snooze(id: str):
    return hygieia.snooze_routine(id)


@app.get(f"{API}/today")
def today(date: str = "", paused: bool = False):
    plan = hygieia.plan(date or None, include_paused=paused)
    return {**plan, "display": today_display(plan)}


# ── display blocks: how Telegram shows a result without the model (hestia_common.display) ──
_STATE = {"due": ("to do", "warning"), "suggested": ("suggested", ""), "done": ("f::done", "success"),
          "partial": ("in part", ""), "blocked": ("not now", ""), "wait": ("later", ""), "ok": ("up to date", "")}


def today_display(plan: dict) -> dict:
    rows = []
    for p in plan.get("routines") or []:
        if p.get("state") in ("off", "rest", "paused") and not p.get("log_id"):
            continue
        label, tone = _STATE.get(p.get("state"), ("", ""))
        label = tr(label) if label else ""
        steps = [x["label"] for x in p.get("steps") or [] if x.get("include")]
        rows.append(item(p.get("name") or tr("Routine"), [label, p.get("reason") or p.get("hint"),
                                                      ", ".join(steps[:4]) + ("…" if len(steps) > 4 else "")], tone=tone))
    due = next((p for p in plan.get("routines") or [] if p.get("state") == "due"), None)
    acts = [action(tr("Done: {0}", due['name'])[:24], "selfcare_log", {"routine": due["name"], "status": "done"}, style="primary")] if due else []
    return display(tr("Self care today"), items=rows, lines=[] if rows else [tr("Nothing scheduled today.")],
                   actions=acts + [action(tr("f::Log"), "selfcare_log"), action(tr("Shopping list"), "selfcare_shopping")])


def overview_display(o: dict) -> dict:
    lines = list(o.get("alerts") or [])
    if o.get("in_use"):
        lines.append(tr("In use: ") + ", ".join(o["in_use"][:6]) + ("…" if len(o["in_use"]) > 6 else ""))
    rows = [item(r["name"], [r.get("slot"), r.get("cadence"), "paused" if r.get("status") == "paused" else ""])
            for r in o.get("routines") or []]
    return display(tr("Self care"), subtitle=o.get("text") or "", lines=lines, items=rows,
                   tone="warning" if o.get("alerts") else "",
                   actions=[action(tr("Today"), "selfcare_today", style="primary"), action(tr("Products"), "selfcare_products"),
                            action(tr("Statistics"), "selfcare_stats")])


# ── logs, journal ────────────────────────────────────────────────────────────
@app.get(f"{API}/logs")
def logs(days: int = 30, routine_id: str = "", product_id: str = ""):
    return {"items": hygieia.logs(days, routine_id, product_id)}


@app.delete(f"{API}/logs/{{id}}")
def log_delete(id: str):
    out = hygieia.delete_log(id)
    signals.changed()
    return out


@app.get(f"{API}/journal")
def journal(area: str = "", days: int = 120):
    return hygieia.journal(area, days)


@app.post(f"{API}/journal")
def journal_add(body: dict = Body(...)):
    out = {"items": hygieia.journal_add(body)}
    signals.changed()
    return out


def _diary_voice(audio: Any, date: str = "") -> dict:
    """B9: a voice note → Echo transcribes it (recording kept) → the day's «day» entry."""
    import base64
    a = audio if isinstance(audio, dict) else {"data_b64": audio}
    try:
        raw = base64.b64decode(a.get("data_b64") or "")
    except (ValueError, TypeError):
        raw = b""
    if not raw:
        raise Invalid(tr("the voice message is missing"))
    heard = voice.transcribe(raw, a.get("mime") or a.get("mime_type") or "audio/ogg", use_case=DIARY_VOICE_USE,
                             keep={"kind": "recording", "client": "hygieia"})
    if not heard:
        logger.warning("[🔄] event=diary_voice_not_heard fallback=ask_again")
        raise Invalid(tr("I couldn't understand the voice message, try again or write it"))
    row = hygieia.journal_voice(heard, date or None)
    signals.changed()
    logger.info("event=diary_voice_saved chars=%d audio=%s", len(row.get("note") or ""), bool(row.get("audio_id")))
    return row


@app.post(f"{API}/journal/voice")
def journal_voice(body: dict = Body(...)):
    audio = body.get("audio") or ({"data_b64": body["audio_b64"], "mime": body.get("mime_type")}
                                  if body.get("audio_b64") else None)
    return {"item": _diary_voice(audio, body.get("date") or "")}


@app.post(f"{API}/wearable")
def wearable(body: dict = Body(...)):
    """Feed ``wearable.daily`` from Hecate (Garmin, W4 B10): the night's sleep in the diary."""
    row = hygieia.sleep_from_wearable(body)
    if row:
        signals.changed()
    return {"status": "ok", "sleep": bool(row)}


@app.delete(f"{API}/journal/{{id}}")
def journal_delete(id: str):
    out = hygieia.delete_journal(id)
    signals.changed()
    return out


# ── statistics, history, alerts ──────────────────────────────────────────────
@app.get(f"{API}/stats")
def stats(days: int = 90):
    return hygieia.stats(max(7, min(days, 730)))


@app.get(f"{API}/timeline")
def timeline(days: int = 365, since: str = "", until: str = ""):
    return {"items": hygieia.timeline(days, since or None, until or None)}


@app.get(f"{API}/period")
def period(date: str = ""):
    return hygieia.period(date)


@app.get(f"{API}/alerts")
def alerts():
    return {"items": hygieia.alerts()}


@app.get(f"{API}/shopping")
def shopping():
    return hygieia.shopping()


@app.get(f"{API}/check")
def check(routine_id: str = "", product: str = "", actives: str = ""):
    return hygieia.check(routine_id, product, [a for a in actives.split(",") if a] or None)


@app.get(f"{API}/summary")
def summary():
    s = hygieia.summary()
    return {"text": s["text"], "alerts": s["alerts"], "in_use": s["in_use"], "plan": s["plan"]}


@app.get(f"{API}/overview")
def overview():
    o = hygieia.overview()
    return {**o, "display": overview_display(o)}


@app.get(f"{API}/export")
def export():
    return {"filename": f"selfcare-{hygieia.today().isoformat()}.json", "data": hygieia.export()}


def _recap_piece(day, nxt) -> dict:
    """Daily recap piece (docs/work/2026-10-20-recap-giornaliero)."""
    return recap.piece("hygieia", tr("Self care"), icon="droplet", emoji="🧴", order=40, **hygieia.recap(day, nxt))


app.include_router(recap.recap_router("hygieia", _recap_piece, today=lambda: hygieia.today()))


@app.get("/api/module/context")
def module_context(budget: int = 400, topic: str = ""):
    """Shared contract of the new modules: a short caveman line the assistant may include. ``topic`` = a signal key
    (``adherence_drop``, ``goal:<routine>``…): the facts behind that signal; unknown topic → the normal line."""
    return {"module": "hygieia", "domain": "selfcare", "updated_at": now_iso(),
            "text": hygieia.context_text(budget, topic)}


# ── quick actions (WebUI Home) ───────────────────────────────────────────────
@app.get(f"{API}/quick/routines")
def quick_routines():
    return hygieia.quick_routines()


@app.post(f"{API}/quick/routine/{{id}}")
def quick_routine(id: str, body: dict = Body(default={})):
    out = hygieia.log_routine(id, body.get("date"), "done", None, body.get("note") or "",
                              source=body.get("source") or "quick")
    signals.changed()
    return {**out, "label": tr("{0} done ✓ {1}", out['name'], out['hint']).strip()}


@app.delete(f"{API}/quick/routine/{{id}}")
def quick_routine_undo(id: str, date: str = ""):
    out = hygieia.undo_log(routine_id=id, day=date or None)
    signals.changed()
    return out


@app.get(f"{API}/quick/products")
def quick_products():
    return hygieia.quick_products()


@app.post(f"{API}/quick/product/{{id}}")
def quick_product(id: str, body: dict = Body(default={})):
    out = hygieia.log_product(id, body.get("date"), body.get("note") or "", source="quick")
    return {**out, "label": tr("{0} used", out['name'])}


@app.delete(f"{API}/quick/product/{{id}}")
def quick_product_undo(id: str, date: str = ""):
    return hygieia.undo_log(product_id=id, day=date or None)


# ── reminders and alerts (agenda jobs → Hermes, one live notification per thing) ──
def _emit(key: str, title: str, text: str, actions: list[dict], level: str = "info", page: str = "today") -> None:
    hub.ok("hermes", "POST", "api/events/ingest", body=reminder_event(
        module="hygieia", domain="selfcare", key=key, kind=key.rsplit(".", 1)[0], title=title, text=text,
        voice=bool(settings.get("hygieia.notifications.voice", True)),
        actions=actions, page=page, level=level), timeout=8)


@app.post(f"{API}/reminders/run")
def reminders_run():
    """Agenda job ``hygieia.planner``: a nudge only for routines with the reminder on that are behind their goal,
    at most ``max_per_week`` a week; Hermes keeps one live reminder per routine and counts the skips itself."""
    out = []
    for d in hygieia.reminder_decisions():
        if not d.get("send"):
            out.append({k: d.get(k) for k in ("routine_id", "send", "why")})
            continue
        p, rid = d["plan"], d["routine_id"]
        actions = [
            {"id": "done", "label": tr("Done"), "text": tr("✅ Done"), "style": "primary", "service": "hygieia", "method": "POST",
             "path": f"{API}/quick/routine/{rid}", "body": {"source": "reminder_button"}, "resolves": True},
            {"id": "skip", "label": tr("Skip"), "text": "⏭ Skip", "service": "hygieia", "method": "POST",
             "path": f"{API}/routines/{rid}/skip", "body": {"source": "reminder_button"}},
            {"id": "week", "label": tr("Not this week"), "text": tr("🌙 Not this week"), "service": "hygieia",
             "method": "POST", "path": f"{API}/routines/{rid}/snooze", "body": {}, "resolves": True},
        ]
        try:
            _emit(f"selfcare.reminder.{rid}", "Self care", hygieia.reminder_text(p), actions, page=f"routine/{rid}")
            hygieia.mark_reminder_sent(rid)
            logger.info("event=selfcare_reminder_sent routine=%s hint=%s", rid, p.get("hint"))
            out.append({"routine_id": rid, "send": True})
        except Exception as exc:
            logger.warning("[🔄] event=selfcare_reminder_emit_failed routine=%s error=%s fallback=next_run", rid, exc)
            out.append({"routine_id": rid, "send": False, "why": "hermes_unreachable"})
    return {"items": out}


@app.post(f"{API}/alerts/run")
def alerts_run():
    """Agenda job ``hygieia.alerts``: expiry / running out / finished-but-in-a-routine, each at most weekly."""
    if not hygieia.setting("hygieia.alerts.enabled", True):
        return {"items": [], "why": "disabled"}
    today = hygieia.today()
    sent = []
    for a in hygieia.alerts():
        key = a["key"].replace(":", ".")
        row = hygieia.store.data("alert", key) or {}
        last = row.get("sent")
        if last and (today - _date.fromisoformat(last)).days < 7:
            continue
        pid = a["product_id"]
        if a["type"] == "expiry":
            actions = [{"id": "discard", "label": tr("Thrown away"), "text": "🗑 Thrown away", "service": "hygieia", "method": "POST",
                        "path": f"{API}/products/{pid}/status", "body": {"status": "discarded"}, "resolves": True}]
        else:
            actions = [{"id": "bought", "label": tr("Bought again"), "text": "🛒 Bought again", "service": "hygieia", "method": "POST",
                        "path": f"{API}/products/{pid}/repurchase", "body": {}, "resolves": True}]
        try:
            _emit(f"selfcare.alert.{key}", "Self care", a["text"], actions, level=a.get("level") or "info",
                  page=f"products/{pid}")
            hygieia.store.upsert("alert", key, {"sent": today.isoformat(), "type": a["type"], "product_id": pid})
            sent.append(a["key"])
        except Exception as exc:
            logger.warning("[🔄] event=selfcare_alert_emit_failed key=%s error=%s fallback=next_run", a["key"], exc)
    logger.info("event=selfcare_alerts_run sent=%d", len(sent))
    return {"items": sent}


# ── reflection signals (agenda job hygieia.signals) ──────────────────────────
@app.post(f"{API}/signals/run")
def signals_run():
    """Agenda job ``hygieia.signals``: re-evaluate the self care signals and weekly metrics, sync to Archive."""
    return signals.run()


def _agenda_rules() -> list[dict]:
    return [
        signals_rule("hygieia", "Self care", path=f"{API}/signals/run", tz=TZ),
        job_rule("hygieia.planner", "Self care reminders (Hygieia)", service="hygieia", path=f"{API}/reminders/run",
                 recurrence="FREQ=DAILY", start_at="2026-01-01T20:30:00", tz=TZ,
                 description="Checks the routines with the reminder on that are behind their goal. At most 2 a week per routine, only one visible at a time."),
        job_rule("hygieia.alerts", "Self care product alerts (Hygieia)", service="hygieia", path=f"{API}/alerts/run",
                 recurrence="FREQ=DAILY", start_at="2026-01-01T10:00:00", tz=TZ,
                 description="Products expiring or running out. One notice per product, no more than one a week."),
    ]


# ── plugin (UI bundle) ───────────────────────────────────────────────────────
ui = PluginClient("hygieia", title="Self care", icon="sparkle", color="pink",
                  description="Routines, products, what to do today in one tap, statistics and history.", dist=UI_DIST,
                  version=SERVICE_VERSION)
ui.webui(
    entry="hygieia.js", api_prefix=f"{API}/",
    pages=[page("today", "Self care", element="hygieia-today", icon="sparkle", order=40,
                help="Today's routines: one tap to mark them done."),
           page("routine", "Routine", element="hygieia-routines", icon="list", order=41, parent="today"),
           page("routine/:id", "Routine", element="hygieia-routine", detail=True, parent="today"),
           page("products", "Products", element="hygieia-products", icon="drop", order=42, parent="today"),
           page("products/:id", "Product", element="hygieia-product", detail=True, parent="today"),
           page("diary", "Diary", element="hygieia-journal", icon="edit", order=43, parent="today"),
           page("stats", "Statistics and history", element="hygieia-stats", icon="chart", order=44, parent="today"),
           page("groceries", "Shopping list", element="hygieia-shopping", icon="cart", order=45, parent="today")],
    widgets=[widget("today", "Today's self care", element="hygieia-today-widget", sizes=["m", "l"], auto=True,
                    open_page="today", icon="sparkle"),
             widget("next", "Next routine", element="hygieia-next-widget", sizes=["s", "m"], open_page="today",
                    icon="clock"),
             widget("products", "Expiring and to buy again", element="hygieia-alerts-widget", sizes=["m", "l"],
                    open_page="groceries", icon="drop"),
             widget("week", "Self care week", element="hygieia-week-widget", sizes=["s", "m", "l"],
                    open_page="stats", icon="calendar")],
    quick_actions=[
        quick_action("done", "Routine done", "POST", f"{API}/quick/routine/{{id}}", icon="check", group="Self care",
                     source=f"{API}/quick/routines", undo={"method": "DELETE", "path": f"{API}/quick/routine/{{id}}"},
                     favorite=True, order=40),
        quick_action("use", "Product used", "POST", f"{API}/quick/product/{{id}}", icon="drop", group="Self care",
                     source=f"{API}/quick/products", undo={"method": "DELETE", "path": f"{API}/quick/product/{{id}}"},
                     order=41),
    ],
)
app.include_router(ui.router())
app.include_router(settings.router())

# ── export / import (hestia_common.transfer; reminder/alert rows are runtime state) ─────────────────────
transfer = Transfer("hygieia", hub, sections=[
    StoreSection("products", "Products", store, ["product", "event"], item_kinds=["product"], icon="drop",
                 subtitle=lambda r: r["data"].get("brand") or ""),
    StoreSection("routine", "Routine", store, ["routine", "version"], item_kinds=["routine"], icon="repeat",
                 subtitle=lambda r: r["data"].get("slot") or "", depends_on=["products", "lists"]),
    StoreSection("log", "Log", store, ["log"], icon="history",
                 title=lambda r: f"{r['data'].get('date')} · {r['data'].get('status') or 'done'}",
                 subtitle=lambda r: r["data"].get("note") or "", depends_on=["routine", "products"]),
    StoreSection("diary", "Diary", store, ["journal"], icon="note",
                 title=lambda r: f"{r['data'].get('date')} · {r['data'].get('area') or ''}",
                 subtitle=lambda r: r["data"].get("note") or ""),
    StoreSection("lists", "Personal lists", store, ["option"], icon="list"),
])
app.include_router(transfer.router())


# ── MCP tools (domain selfcare; Oracle calls them, the logic stays here) ─────
def _t(fn):
    def run(**kw):
        try:
            return fn(**{k: v for k, v in kw.items() if v is not None})
        except (Invalid, NotFound, Conflict) as exc:
            return {"error": str(exc), **(getattr(exc, "detail", {}) or {})}
    return run


def _product_short(p: dict) -> dict:
    out = {k: p.get(k) for k in ("id", "name", "brand", "category", "status", "level", "opened_at", "expiry", "expires_in",
                                 "uses", "last_used", "rating", "verdict", "price") if p.get(k) not in (None, "", [])}
    if p.get("actives"):
        out["actives"] = [a["name"] for a in p["actives"]]
    return out


try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router, mount_missing_rest_routes

    def _need_routine(name: str) -> dict:
        r = hygieia.find_routine(name)
        if not r:
            raise NotFound(tr("routine '{0}' not found", name))
        return r

    def _need_product(name: str) -> dict:
        p = hygieia.find_product(name)
        if not p:
            raise NotFound(tr("product '{0}' not found", name))
        return p

    def _overview() -> dict:
        return hygieia.overview()

    def _today(date: str = "") -> dict:
        plan = hygieia.plan(date or None)
        return {"date": plan["date"], "routines": [
            {"name": p["name"], "state": p["state"], "hint": p["hint"], "reason": p["reason"],
             "steps": [s["label"] + (f" ({s['amount']})" if s["amount"] else "") for s in p["steps"] if s["include"]],
             "not_today": [f"{s['label']}: {s['reason']}" for s in p["steps"] if not s["include"] and s["reason"]],
             "warnings": p["warnings"]} for p in plan["routines"] if p["state"] not in ("off", "rest") or p["log_id"]]}

    def _log(routine: str = "", status: str = "done", skipped_steps: list | None = None, product: str = "",
             date: str = "", note: str = "") -> dict:
        if product and not routine:
            p = _need_product(product)
            out = hygieia.log_product(p["id"], date or None, note, source="assistant")
            return {"logged": out["name"], "date": out["date"]}
        r = _need_routine(routine)
        steps = None
        if skipped_steps:
            plan = hygieia.routine_plan(r["id"], date or None)
            skip = [catalog.slug(x) for x in skipped_steps]
            steps = [s["step_id"] for s in plan["steps"] if s["include"]
                     and not any(k in catalog.slug(s["label"]) for k in skip)]
        out = hygieia.log_routine(r["id"], date or None, status if status in ("done", "partial", "skipped") else "done",
                                  steps, note, source="assistant")
        signals.changed()
        return {"logged": out["name"], "status": out["status"], "date": out["date"], "goal": out["hint"]}

    def _products(query: str = "", area: str = "", status: str = "current", active: str = "", category: str = "") -> dict:
        items = hygieia.products(query, area, category, "" if status == "all" else status, active)
        return {"count": len(items), "items": [_product_short(p) for p in items[:40]]}

    def _product_get(product: str = "") -> dict:
        d = hygieia.product_detail(_need_product(product)["id"])
        return {**_product_short(d), "routines": [r["name"] for r in d["routines"]], "finish_estimate": d["finish_estimate"],
                "notes": d.get("notes"), "events": [f"{e['date']} {e.get('text')}" for e in d["events"][:10]],
                "previous": [f"{s.get('purchased_at')} → {s.get('finished_at') or s.get('status')}" for s in d["siblings"][:5]]}

    def _product_add(name: str = "", brand: str = "", category: str = "", areas: list | None = None,
                     actives: list | None = None, size: float | None = None, unit: str = "", price: float | None = None,
                     status: str = "in_use", pao_months: int | None = None, notes: str = "", favorite: bool = False) -> dict:
        body = {"name": name, "brand": brand, "category": catalog.slug(category) if category else "", "areas": areas or [],
                "actives": actives or [], "size": size, "unit": unit or "ml", "price": price, "status": status or "in_use",
                "pao_months": pao_months, "notes": notes, "favorite": favorite}
        out = hygieia.save_product(body, source="assistant")
        return {"saved": True, **_product_short(out)}

    def _product_update(product: str = "", status: str = "", level: str = "", rating: int | None = None,
                        verdict: str = "", favorite: bool | None = None, notes: str = "", price: float | None = None,
                        opened_at: str = "", expires_at: str = "", repurchased: bool = False) -> dict:
        p = _need_product(product)
        if repurchased:
            out = hygieia.repurchase(p["id"], source="assistant")
            return {"saved": True, "new_item": _product_short(out)}
        if status:
            hygieia.set_status(p["id"], status, source="assistant")
        body = {k: v for k, v in {"level": level, "rating": rating, "verdict": verdict, "notes": notes, "price": price,
                                  "opened_at": opened_at, "expires_at": expires_at}.items() if v not in (None, "")}
        if favorite is not None:
            body["favorite"] = favorite
        out = hygieia.save_product(body, id=p["id"], source="assistant") if body else hygieia.product_detail(p["id"])
        return {"saved": True, **_product_short(out)}

    def _routines() -> dict:
        return {"items": [{"name": r["name"], "slot": catalog.SLOTS.get(r.get("slot"), r.get("slot")),
                           "cadence": r["cadence_label"], "status": r.get("status"), "today": r["state"], "hint": r["hint"],
                           "reminder": r.get("reminder"), "steps": r["step_count"]} for r in hygieia.routines()]}

    def _routine_get(routine: str = "") -> dict:
        d = hygieia.routine_detail(_need_routine(routine)["id"])
        return {"name": d["name"], "cadence": d["cadence_label"], "slot": d.get("slot"), "status": d.get("status"),
                "version": d.get("version"), "reminder": d.get("reminder"),
                "steps": [{"label": s.get("label") or (s.get("product") or {}).get("name"), "amount": s.get("amount"),
                           "wait_min": round((s.get("wait_seconds") or 0) / 60), "cadence": s.get("cadence_label"),
                           "paused_until": s.get("paused_until"), "optional": s.get("optional")} for s in d["steps"]],
                "today": {"state": d["plan"]["state"], "reason": d["plan"]["reason"], "hint": d["plan"]["hint"]},
                "stats": {k: d["stats"][k] for k in ("total", "skipped", "streak", "adherence", "last_done")},
                "history": [f"v{v['version']} {v['valid_from']}: {v.get('reason') or v.get('diff')}" for v in d["versions"][:8]],
                "notes": [n["text"] for n in d["check"]]}

    def _cadence(mode: str = "", times: int | None = None, per: str = "", days: list | None = None) -> dict | None:
        if not mode and not times:
            return None
        dd = [int(d) if str(d).isdigit() else weekday_of(str(d)) for d in days or []]
        return {"mode": mode or "target", "times": times or 1, "per": per or "week", "days": dd}

    def _step_from_text(text: str) -> dict:
        p = hygieia.find_product(text, ("in_use", "stock", "paused"))
        return {"product_id": p["id"]} if p else {"label": text}

    def _routine_create(name: str = "", slot: str = "anytime", areas: list | None = None, steps: list | None = None,
                        cadence_mode: str = "target", times: int | None = None, per: str = "week", days: list | None = None,
                        reminder: bool = False, favorite: bool = False) -> dict:
        body = {"name": name, "slot": slot, "areas": areas or [], "reminder": reminder, "favorite": favorite,
                "cadence": _cadence(cadence_mode, times or (1 if cadence_mode == "target" else None), per, days),
                "steps": [_step_from_text(s) for s in steps or []]}
        d = hygieia.save_routine(body, reason=tr("created by the assistant"), source="assistant")
        return {"saved": True, "name": d["name"], "cadence": d["cadence_label"],
                "steps": [s.get("label") or (s.get("product") or {}).get("name") for s in d["steps"]],
                "notes": [n["text"] for n in d["check"]]}

    def _routine_edit(routine: str = "", reason: str = "", add_step: str = "", position: int | None = None,
                      remove_step: str = "", step: str = "", step_times: int | None = None, step_per: str = "",
                      pause_days: int | None = None, amount: str = "", wait_minutes: int | None = None,
                      name: str = "", cadence_mode: str = "", times: int | None = None, per: str = "",
                      days: list | None = None, status: str = "", reminder: bool | None = None,
                      favorite: bool | None = None, plan_with: str = "") -> dict:
        r = _need_routine(routine)
        steps = [dict(s) for s in r.get("steps") or []]

        def match(text: str) -> dict | None:
            k = catalog.slug(text)
            for s in steps:
                label = s.get("label") or (hygieia.store.data("product", s.get("product_id") or "") or {}).get("name") or ""
                if k and k in catalog.slug(label):
                    return s
            return None

        body: dict[str, Any] = {}
        if remove_step:
            s = match(remove_step)
            if not s:
                return {"error": tr("step '{0}' not found in {1}", remove_step, r['name'])}
            steps.remove(s)
        if add_step:
            new = _step_from_text(add_step)
            if amount:
                new["amount"] = amount
            if wait_minutes:
                new["wait_seconds"] = int(wait_minutes) * 60
            steps.insert(max(0, min(len(steps), (position or len(steps) + 1) - 1)), new)
        if step:
            s = match(step)
            if not s:
                return {"error": tr("step '{0}' not found in {1}", step, r['name'])}
            if step_times is not None:
                s["cadence"] = None if step_times == 0 else {"mode": "target", "times": step_times, "per": step_per or "week"}
            if pause_days is not None:
                s["paused_until"] = None if pause_days == 0 else (hygieia.today() + timedelta(days=pause_days)).isoformat()
            if amount and not add_step:
                s["amount"] = amount
            if wait_minutes is not None and not add_step:
                s["wait_seconds"] = int(wait_minutes) * 60
        if remove_step or add_step or step:
            body["steps"] = steps
        if name:
            body["name"] = name
        c = _cadence(cadence_mode, times, per, days)
        if c:
            body["cadence"] = c
        if status:
            body["status"] = status
        if reminder is not None:
            body["reminder"] = reminder
        if favorite is not None:
            body["favorite"] = favorite
        if plan_with:
            body["plan_with"] = "" if catalog.slug(plan_with) in ("none", "no", "none") else plan_with
        if not body:
            return {"error": tr("no change given")}
        d = hygieia.save_routine(body, id=r["id"], reason=reason or tr("edited by the assistant"), source="assistant")
        return {"saved": True, "name": d["name"], "version": d.get("version"), "cadence": d["cadence_label"],
                "steps": [(s.get("label") or (s.get("product") or {}).get("name"))
                          + (f" [{s['cadence_label']}]" if s.get("cadence_label") else "")
                          + (tr(" [paused until {0}]", s['paused_until']) if s.get("paused_until") else "") for s in d["steps"]],
                "notes": [n["text"] for n in d["check"]], "undo": "selfcare_undo_routine"}

    def _undo_routine(routine: str = "") -> dict:
        d = hygieia.undo_routine(_need_routine(routine)["id"], source="assistant")
        return {"restored": d["name"], "version": d.get("version")}

    def _journal_add(area: str = "", scores: dict | None = None, note: str = "", tags: list | None = None,
                     date: str = "") -> dict:
        rows = hygieia.journal_add({"date": date or None, "entries": [{"area": area, "scores": scores or {}, "note": note,
                                                                      "tags": tags or []}]}, source="assistant")
        signals.changed()
        return {"saved": len(rows)}

    def _stats(days: int = 90) -> dict:
        s = hygieia.stats(max(7, min(days, 730)))
        return {"routines": [{k: r[k] for k in ("name", "cadence", "total", "skipped", "streak", "adherence", "last_done")}
                             for r in s["routines"]], "top_products": s["top_products"][:8], "week": s["week"],
                "spend_last_months": [x for x in s["spend"] if x["amount"]][-6:]}

    def _timeline(days: int = 90, since: str = "", until: str = "") -> dict:
        return {"items": [f"{t['date']} · {t['title']}: {t['text']}" for t in hygieia.timeline(days, since or None, until or None)[:60]]}

    def _period(date: str = "") -> dict:
        return hygieia.period(date)

    def _check(routine: str = "", product: str = "", actives: list | None = None) -> dict:
        rid = _need_routine(routine)["id"] if routine else ""
        return hygieia.check(rid, product, actives)

    def _shopping() -> dict:
        s = hygieia.shopping()
        return {k: [f"{p.get('brand') + ' ' if p.get('brand') else ''}{p['name']}" + (f" — {p['why']}" if p.get("why") else "")
                    for p in s[k]] for k in ("wishlist", "restock", "repurchase")}

    S = {"type": "string"}
    I = {"type": "integer"}
    N = {"type": "number"}
    B = {"type": "boolean"}
    L = {"type": "array", "items": {"type": "string"}}
    O = {"type": "object"}
    G = "selfcare"
    _tools = [
        MCPTool(name="selfcare_summary", description=("The user's self care: routines (with steps and frequency), products in use, warnings (expiry, "
                                                      "to buy again) and what is left today. Use it first for any question on skincare, hair, body, "
                                                      "cosmetics."), parameters={"type": "object", "properties": {}},
                handler=_t(_overview), title="Self care summary", path=f"{API}/overview", clients=["telegram", "ui"], telegram_group="selfcare",
                telegram={"section": "Today", "summary": True}),
        MCPTool(name="selfcare_today", description=("What to do today (or on 'date'): routines with state (due = to do, suggested, blocked = not "
                                                    "today and why, done), steps for tonight, steps excluded today (e.g. retinol vs acid)."), parameters={"type": "object", "properties": {"date": S}},
                handler=_t(_today), title="Self care today", path=f"{API}/today", clients=["telegram", "ui"], telegram_group="selfcare",
                telegram={"section": "Today", "primary": 1, "label": "Today"}),
        MCPTool(name="selfcare_log", description=("Log: routine done (status done|partial|skipped, skipped_steps = skipped steps by name) or an "
                                                  "extra use of a product (product, e.g. 'mask'). date YYYY-MM-DD, default today."), parameters={"type": "object", "properties": {
                    "routine": S, "status": S, "skipped_steps": L, "product": S, "date": S, "note": S}},
                handler=_t(_log), title="Mark done", method="POST", path=f"{API}/log", clients=["telegram", "ui"],
                telegram_group="selfcare",
                telegram={"section": "Today", "primary": 2}),
        MCPTool(name="selfcare_products", description=("Search products (query name/brand, area face|hair|body…, status current (default) | all | "
                                                       "in_use | stock | wishlist | finished, active e.g. retinol)."),
                parameters={"type": "object", "properties": {"query": S, "area": S, "status": S, "active": S, "category": S}},
                handler=_t(_products), title="Products", path=f"{API}/products", clients=["telegram", "ui"],
                telegram_group="selfcare",
                telegram={"section": "Products", "primary": 4}),
        MCPTool(name="selfcare_product_get", description=("Detail of a product: uses, expiry, estimate of when it runs out, routines using it, history, "
                                                          "previous packs."),
                parameters={"type": "object", "properties": {"product": S}, "required": ["product"]},
                handler=_t(_product_get), title="Product detail", path=f"{API}/products/{{id}}", clients=["ui"],
                telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Products"}),
        MCPTool(name="selfcare_product_add", description=("Add a product (e.g. 'I bought serum X 30ml'). status in_use (open, default) | stock (closed) | wishlist. actives = slugs (retinol, niacinamide, aha_glycolic, bha_salicylic, vitamin_c…). category e.g. cleanser, serum, cream, spf, shampoo."),
                parameters={"type": "object", "properties": {"name": S, "brand": S, "category": S, "areas": L, "actives": L,
                                                             "size": N, "unit": S, "price": N, "status": S, "pao_months": I,
                                                             "notes": S, "favorite": B}, "required": ["name"]},
                handler=_t(_product_add), title="Add product", method="POST", path=f"{API}/products",
                clients=["telegram", "ui"], telegram_group="selfcare",
                telegram={"section": "Products"}),
        MCPTool(name="selfcare_product_update", description=("Update a product: status in_use (open) | finished | discarded | paused | stock, level "
                                                             "full|3/4|half|1/4|almost_empty, rating 1-5, verdict repurchase|maybe|never, repurchased=true if "
                                                             "bought again (new pack)."),
                parameters={"type": "object", "properties": {"product": S, "status": S, "level": S, "rating": I, "verdict": S,
                                                             "favorite": B, "notes": S, "price": N, "opened_at": S,
                                                             "expires_at": S, "repurchased": B}, "required": ["product"]},
                handler=_t(_product_update), title="Update product", method="PUT", path=f"{API}/products/{{id}}",
                clients=["telegram", "ui"], telegram_group="selfcare",
                telegram={"section": "Products"}),
        MCPTool(name="selfcare_routines", description="The routines with frequency, today's state and goal (e.g. 1/2 a week).",
                parameters={"type": "object", "properties": {}}, handler=_t(_routines), title="Routine",
                path=f"{API}/routines", clients=["telegram", "ui"], telegram_group="selfcare",
                telegram={"section": "Routine", "primary": 3}),
        MCPTool(name="selfcare_routine_get", description=("One routine: steps in order with amounts, waits and own frequency, statistics, version history, "
                                                          "compatibility warnings."),
                parameters={"type": "object", "properties": {"routine": S}, "required": ["routine"]},
                handler=_t(_routine_get), title="Routine detail", path=f"{API}/routines/{{id}}", clients=["ui"],
                telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Routine"}),
        MCPTool(name="selfcare_routine_create", description=("Create a routine. steps = product names (looked up in the inventory) or descriptions. "
                                                             "cadence_mode daily | fixed_days (days Mon..Sun) | target (times per week|month, default) | "
                                                             "as_needed. Only after the user's yes."),
                parameters={"type": "object", "properties": {"name": S, "slot": S, "areas": L, "steps": L, "cadence_mode": S,
                                                             "times": I, "per": S, "days": L, "reminder": B, "favorite": B},
                            "required": ["name"]},
                handler=_t(_routine_create), title="Create routine", method="POST", path=f"{API}/routines",
                clients=["ui"], telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Routine"}),
        MCPTool(name="selfcare_routine_edit", description=("Edit a routine (creates a new version, undoable): add_step (+position, amount, wait_minutes), "
                                                           "remove_step, step + step_times/step_per (the step's own frequency, 0 = always) or pause_days "
                                                           "(e.g. 'no retinol for a week' = step retinol, pause_days 7; 0 = resume), "
                                                           "cadence_mode/times/per/days of the routine, status active|paused, reminder, favorite, plan_with "
                                                           "= put the routine in the week plan only on days with this thing (e.g. 'workout' = training "
                                                           "days; 'none' removes it). reason = why (goes into the history)."),
                parameters={"type": "object", "properties": {
                    "routine": S, "reason": S, "add_step": S, "position": I, "remove_step": S, "step": S, "step_times": I,
                    "step_per": S, "pause_days": I, "amount": S, "wait_minutes": I, "name": S, "cadence_mode": S,
                    "times": I, "per": S, "days": L, "status": S, "reminder": B, "favorite": B, "plan_with": S},
                    "required": ["routine"]},
                handler=_t(_routine_edit), title="Edit routine", method="PUT", path=f"{API}/routines/{{id}}",
                clients=["ui"], telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Routine"}),
        MCPTool(name="selfcare_undo_routine", description="Undo the last change to the steps of a routine.",
                parameters={"type": "object", "properties": {"routine": S}, "required": ["routine"]},
                handler=_t(_undo_routine), title="Undo routine change", method="POST",
                path=f"{API}/routines/{{id}}/undo", clients=["ui"], telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Routine"}),
        MCPTool(name="selfcare_journal_add", description=("Diary (if active): scores 1-5 per area, e.g. area face scores {pimples: 2, hydration: 4}, "
                                                          "hair {hair_loss: 3}; notes and tags (stress, sun, cycle…)."),
                parameters={"type": "object", "properties": {"area": S, "scores": O, "note": S, "tags": L, "date": S},
                            "required": ["area"]},
                handler=_t(_journal_add), title="Write in the diary", method="POST", path=f"{API}/journal", clients=["ui"],
                telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Diary"}),
        MCPTool(name="selfcare_diary_voice", description=("Spoken diary: the user tells the day in a voice message; it is transcribed and saved in the "
                                                          "diary (area day). Offered after the evening recap."),
                parameters={"type": "object", "properties": {
                    "audio": {"type": "string", "contentMediaType": "audio/ogg", "title": "Your voice message"},
                    "date": S}, "required": ["audio"]},
                handler=_t(lambda audio, date="": {"item": _diary_voice(audio, date)}), title="Tell me about your day",
                method="POST", path=f"{API}/journal/voice", clients=["telegram", "ui"], telegram_group="selfcare",
                telegram={"section": "Diary"}),
        MCPTool(name="selfcare_stats", description=("Statistics: consistency per routine (streak, % of periods kept), most used products, spending "
                                                    "per month."), parameters={"type": "object", "properties": {"days": I}},
                handler=_t(_stats), title="Self care statistics", path=f"{API}/stats", clients=["ui"],
                telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Statistics", "label": "Statistics"}),
        MCPTool(name="selfcare_timeline", description=("What changed over time: routine versions, products opened/finished/replaced, diary. since/until "
                                                       "YYYY-MM-DD."),
                parameters={"type": "object", "properties": {"days": I, "since": S, "until": S}}, handler=_t(_timeline),
                title="Self care history", path=f"{API}/timeline", clients=["ui"], telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Diary", "label": "alt::History"}),
        MCPTool(name="selfcare_period", description="Routines and products in use on a given date (e.g. 'what was I using in March').",
                parameters={"type": "object", "properties": {"date": S}, "required": ["date"]}, handler=_t(_period),
                title="Self care on a date", path=f"{API}/period", clients=["ui"], telegram_visible=False,
                telegram_group="selfcare",
                telegram={"section": "Diary", "label": "On a date"}),
        MCPTool(name="selfcare_check", description=("Compatibility of actives (advice, never a block): of a routine, or of a product / list of "
                                                    "actives against those in use."),
                parameters={"type": "object", "properties": {"routine": S, "product": S, "actives": L}},
                handler=_t(_check), title="Compatibility", path=f"{API}/check", clients=["ui"],
                telegram_visible=False, telegram_group="selfcare",
                telegram={"section": "Products"}),
        MCPTool(name="selfcare_shopping", description=("Self care shopping list: wishes, to buy again (running out, finished in a routine), finished "
                                                       "with the verdict 'I would buy it again'."), parameters={"type": "object", "properties": {}},
                handler=_t(_shopping), title="Shopping list", path=f"{API}/shopping", clients=["telegram", "ui"],
                telegram_group="selfcare",
                telegram={"section": "Products", "primary": 5}),
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
                    kw[k] = is_yes(v)
                elif typ == "array":
                    kw[k] = [x.strip() for x in v.split(",") if x.strip()]
            return inner(**{k: v for k, v in kw.items() if k in props})
        return run

    for _tool in _tools:
        # one REST path per tool whose arguments are exactly the tool's (served by mount_missing_rest_routes)
        _tool.path = f"{API}/tools/{_tool.name.removeprefix('selfcare_')}"
        _tool.handler = _coerced(_tool)
    app.include_router(create_mcp_router(_tools, service_name="hygieia"))
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=hygieia reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_hygieia"))
try:
    mount_missing_rest_routes(app, _tools, service_name="hygieia")
except NameError:
    pass


# ── Hub registration ─────────────────────────────────────────────────────────
def _registration() -> dict:
    caps = {"when_to_use": "self care: skincare, routines, wellbeing diary, sleep, mood", "manual": "Self-care routines, products, wellbeing diary (always on), notes on sleep and mood.",
            "mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": ["selfcare"],
            "context_endpoint": "/api/module/context", **recap.capabilities(), **voice_capabilities(VOICE_USECASES),
            **feed_capabilities({"wearable.daily": f"{API}/wearable"})}
    try:
        caps.update(ui.capabilities(SERVICE_BASE_URL))
        caps.update(transfer.capabilities())
    except Exception as exc:
        logger.warning("[🔄] event=hygieia_ui_manifest_failed error=%s fallback=no_ui", exc)
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
    """Load the mirror in the background (never block startup on Archive)."""
    import time
    for attempt in range(1, 1000):
        try:
            if store.refresh(force=True):
                signals.changed()           # time-based facts may have moved while the service was down
                return
        except Exception as exc:
            logger.warning("[🔄] event=hygieia_warmup_failed attempt=%d error=%s", attempt, exc)
        time.sleep(min(60, 5 * attempt))


@app.on_event("startup")
def startup():
    try:
        _register()
    except Exception as exc:
        logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
    from hestia_common.startup_utils import start_hub_keepalive
    start_hub_keepalive(_register, logger=logger, name="hygieia-hub-keepalive")
    settings.start()
    agenda.register_async(_agenda_rules)
    threading.Thread(target=_warm_up, daemon=True, name="hygieia-warmup").start()

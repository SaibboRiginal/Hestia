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

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _shared = Path(__file__).resolve().parents[2] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

from hestia_common.agenda_client import AgendaClient, job_rule
from hestia_common.plugin_client import PluginClient, page, quick_action, widget
from hestia_common.settings_client import SettingsClient, setting

from .core import catalog
from .core.hub import Hub
from .core.planner import cadence_label
from .core.service import Conflict, Hygieia, Invalid, NotFound
from .core.store import Store, StoreUnavailable, now_iso

logger, log_buffer = setup_service_logging("hestia_hygieia")

SERVICE_NAME = os.getenv("SERVICE_NAME", "hygieia")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_hygieia:19018")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "module")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "module,selfcare,context").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:domain,domain:selfcare,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
UI_DIST = os.getenv("HYGIEIA_UI_DIST", "/code/ui/dist")
TZ = os.getenv("TZ") or "Europe/Rome"
API = "/api/selfcare"

# ── settings (Themis) ────────────────────────────────────────────────────────
settings = SettingsClient("hygieia")
settings.declare([
    setting("hygieia.week_start", "Inizio settimana", "enum", "monday", group="Generale",
            options=[("monday", "Lunedì"), ("sunday", "Domenica")], help="Per gli obiettivi «N volte a settimana»."),
    setting("hygieia.currency", "Valuta", "string", "EUR", group="Generale"),
    setting("hygieia.default_pao_months", "Durata dopo l'apertura", "int", 12, group="Prodotti", min=1, max=60, unit="mesi",
            help="Quando il prodotto non indica il PAO (il barattolino «12M»)."),
    setting("hygieia.reminders.enabled", "Promemoria", "bool", True, group="Promemoria",
            help="Interruttore generale. Ogni routine resta senza promemoria finché non lo attivi su quella routine."),
    setting("hygieia.reminders.max_per_week", "Promemoria massimi a settimana", "int", 2, group="Promemoria", min=1, max=7,
            help="Per ogni routine. Uno solo resta visibile e dice quante volte l'hai saltata.",
            depends_on={"key": "hygieia.reminders.enabled", "equals": True}),
    setting("hygieia.alerts.enabled", "Avvisi prodotti", "bool", True, group="Avvisi",
            help="Scadenze e prodotti che stanno finendo, uno per prodotto."),
    setting("hygieia.alerts.expiry_days", "Avviso scadenza", "int", 30, group="Avvisi", min=1, max=180, unit="giorni",
            depends_on={"key": "hygieia.alerts.enabled", "equals": True}),
    setting("hygieia.alerts.restock_days", "Avviso da ricomprare", "int", 14, group="Avvisi", min=1, max=90, unit="giorni",
            help="Quando la stima dice che finisce entro questi giorni.",
            depends_on={"key": "hygieia.alerts.enabled", "equals": True}),
])

hub = Hub(HUB_API_URL)
store = Store(hub)
hygieia = Hygieia(store, settings.get, tz_name=TZ)
agenda = AgendaClient("hygieia", HUB_API_URL)

app = FastAPI(title="Hestia-Hygieia", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
    return JSONResponse(status_code=503, content={"detail": "archivio non raggiungibile, riprova tra poco"})


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
    return {**out, "label": f"{out['name']} ricomprato"}


@app.post(f"{API}/products/{{id}}/use")
def product_use(id: str, body: dict = Body(default={})):
    out = hygieia.log_product(id, body.get("date"), body.get("note") or "")
    return {**out, "label": f"{out['name']} usato"}


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
    return {**out, "label": f"{out['name']} fatta"}


@app.delete(f"{API}/routines/{{id}}/done")
def routine_undone(id: str, date: str = ""):
    return hygieia.undo_log(routine_id=id, day=date or None)


@app.post(f"{API}/routines/{{id}}/skip")
def routine_skip(id: str, body: dict = Body(default={})):
    out = hygieia.log_routine(id, body.get("date"), "skipped", None, body.get("note") or "", source=body.get("source") or "webui")
    return {**out, "label": f"{out['name']} saltata"}


@app.post(f"{API}/routines/{{id}}/snooze")
def routine_snooze(id: str):
    return hygieia.snooze_routine(id)


@app.get(f"{API}/today")
def today(date: str = "", paused: bool = False):
    return hygieia.plan(date or None, include_paused=paused)


# ── logs, journal ────────────────────────────────────────────────────────────
@app.get(f"{API}/logs")
def logs(days: int = 30, routine_id: str = "", product_id: str = ""):
    return {"items": hygieia.logs(days, routine_id, product_id)}


@app.delete(f"{API}/logs/{{id}}")
def log_delete(id: str):
    return hygieia.delete_log(id)


@app.get(f"{API}/journal")
def journal(area: str = "", days: int = 120):
    return hygieia.journal(area, days)


@app.post(f"{API}/journal")
def journal_add(body: dict = Body(...)):
    return {"items": hygieia.journal_add(body)}


@app.delete(f"{API}/journal/{{id}}")
def journal_delete(id: str):
    return hygieia.delete_journal(id)


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
    return hygieia.overview()


@app.get(f"{API}/export")
def export():
    return {"filename": f"selfcare-{hygieia.today().isoformat()}.json", "data": hygieia.export()}


@app.get("/api/module/context")
def module_context(budget: int = 400):
    """Shared contract of the new modules: a short caveman line the assistant may include."""
    return {"module": "hygieia", "domain": "selfcare", "updated_at": now_iso(), "text": hygieia.context_text(budget)}


# ── quick actions (WebUI Home) ───────────────────────────────────────────────
@app.get(f"{API}/quick/routines")
def quick_routines():
    return hygieia.quick_routines()


@app.post(f"{API}/quick/routine/{{id}}")
def quick_routine(id: str, body: dict = Body(default={})):
    out = hygieia.log_routine(id, body.get("date"), "done", None, body.get("note") or "",
                              source=body.get("source") or "quick")
    return {**out, "label": f"{out['name']} fatta ✓ {out['hint']}".strip()}


@app.delete(f"{API}/quick/routine/{{id}}")
def quick_routine_undo(id: str, date: str = ""):
    return hygieia.undo_log(routine_id=id, day=date or None)


@app.get(f"{API}/quick/products")
def quick_products():
    return hygieia.quick_products()


@app.post(f"{API}/quick/product/{{id}}")
def quick_product(id: str, body: dict = Body(default={})):
    out = hygieia.log_product(id, body.get("date"), body.get("note") or "", source="quick")
    return {**out, "label": f"{out['name']} usato"}


@app.delete(f"{API}/quick/product/{{id}}")
def quick_product_undo(id: str, date: str = ""):
    return hygieia.undo_log(product_id=id, day=date or None)


# ── reminders and alerts (agenda jobs → Hermes, one live notification per thing) ──
def _emit(key: str, title: str, text: str, actions: list[dict], level: str = "info") -> None:
    hub.ok("hermes", "POST", "api/events/ingest", body={
        "event_type": "service.action_required", "domain": "selfcare", "entity_id": key,
        "payload": {"kind": key.rsplit(".", 1)[0], "service": "hygieia", "source": "hygieia", "domain": "selfcare",
                    "_source": "hygieia", "_title": title, "target": "owner", "replaces": key, "level": level,
                    "_message": text, "_actions": actions}}, timeout=8)


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
            {"id": "done", "label": "Fatto", "text": "✅ Fatto", "style": "primary", "service": "hygieia", "method": "POST",
             "path": f"{API}/quick/routine/{rid}", "body": {"source": "reminder_button"}, "resolves": True},
            {"id": "skip", "label": "Salta", "text": "⏭ Salta", "service": "hygieia", "method": "POST",
             "path": f"{API}/routines/{rid}/skip", "body": {"source": "reminder_button"}},
            {"id": "week", "label": "Non questa settimana", "text": "🌙 Non questa settimana", "service": "hygieia",
             "method": "POST", "path": f"{API}/routines/{rid}/snooze", "body": {}, "resolves": True},
        ]
        try:
            _emit(f"selfcare.reminder.{rid}", "Self care", hygieia.reminder_text(p), actions)
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
            actions = [{"id": "discard", "label": "Buttato", "text": "🗑 Buttato", "service": "hygieia", "method": "POST",
                        "path": f"{API}/products/{pid}/status", "body": {"status": "discarded"}, "resolves": True}]
        else:
            actions = [{"id": "bought", "label": "Ricomprato", "text": "🛒 Ricomprato", "service": "hygieia", "method": "POST",
                        "path": f"{API}/products/{pid}/repurchase", "body": {}, "resolves": True}]
        try:
            _emit(f"selfcare.alert.{key}", "Self care", a["text"], actions, level=a.get("level") or "info")
            hygieia.store.upsert("alert", key, {"sent": today.isoformat(), "type": a["type"], "product_id": pid})
            sent.append(a["key"])
        except Exception as exc:
            logger.warning("[🔄] event=selfcare_alert_emit_failed key=%s error=%s fallback=next_run", a["key"], exc)
    logger.info("event=selfcare_alerts_run sent=%d", len(sent))
    return {"items": sent}


def _agenda_rules() -> list[dict]:
    return [
        job_rule("hygieia.planner", "Promemoria self care (Hygieia)", service="hygieia", path=f"{API}/reminders/run",
                 recurrence="FREQ=DAILY", start_at="2026-01-01T20:30:00", tz=TZ,
                 description="Controlla le routine con il promemoria attivo che sono indietro con l'obiettivo. Al massimo "
                             "2 a settimana per routine, uno solo visibile alla volta."),
        job_rule("hygieia.alerts", "Avvisi prodotti self care (Hygieia)", service="hygieia", path=f"{API}/alerts/run",
                 recurrence="FREQ=DAILY", start_at="2026-01-01T10:00:00", tz=TZ,
                 description="Prodotti in scadenza o che stanno finendo. Un avviso per prodotto, non più di uno a settimana."),
    ]


# ── plugin (UI bundle) ───────────────────────────────────────────────────────
ui = PluginClient("hygieia", title="Self care", icon="sparkle", color="pink",
                  description="Routine, prodotti, cosa fare oggi in un tocco, statistiche e storia.", dist=UI_DIST,
                  version=SERVICE_VERSION)
ui.webui(
    entry="hygieia.js", api_prefix=f"{API}/",
    pages=[page("oggi", "Self care", element="hygieia-today", icon="sparkle", order=40,
                help="Le routine di oggi: un tocco per segnarle fatte."),
           page("routine", "Routine", element="hygieia-routines", icon="list", order=41, parent="oggi"),
           page("routine/:id", "Routine", element="hygieia-routine", detail=True, parent="oggi"),
           page("prodotti", "Prodotti", element="hygieia-products", icon="drop", order=42, parent="oggi"),
           page("prodotti/:id", "Prodotto", element="hygieia-product", detail=True, parent="oggi"),
           page("diario", "Diario", element="hygieia-journal", icon="edit", order=43, parent="oggi"),
           page("statistiche", "Statistiche e storia", element="hygieia-stats", icon="chart", order=44, parent="oggi"),
           page("spesa", "Lista spesa", element="hygieia-shopping", icon="cart", order=45, parent="oggi")],
    widgets=[widget("oggi", "Self care di oggi", element="hygieia-today-widget", sizes=["m", "l"], auto=True,
                    open_page="oggi", icon="sparkle"),
             widget("prossima", "Prossima routine", element="hygieia-next-widget", sizes=["s", "m"], open_page="oggi",
                    icon="clock"),
             widget("prodotti", "Scadenze e da ricomprare", element="hygieia-alerts-widget", sizes=["m", "l"],
                    open_page="spesa", icon="drop"),
             widget("settimana", "Settimana self care", element="hygieia-week-widget", sizes=["s", "m", "l"],
                    open_page="statistiche", icon="calendar")],
    quick_actions=[
        quick_action("fatta", "Routine fatta", "POST", f"{API}/quick/routine/{{id}}", icon="check", group="Self care",
                     source=f"{API}/quick/routines", undo={"method": "DELETE", "path": f"{API}/quick/routine/{{id}}"},
                     favorite=True, order=40),
        quick_action("uso", "Prodotto usato", "POST", f"{API}/quick/product/{{id}}", icon="drop", group="Self care",
                     source=f"{API}/quick/products", undo={"method": "DELETE", "path": f"{API}/quick/product/{{id}}"},
                     order=41),
    ],
)
app.include_router(ui.router())
app.include_router(settings.router())


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
            raise NotFound(f"routine '{name}' non trovata")
        return r

    def _need_product(name: str) -> dict:
        p = hygieia.find_product(name)
        if not p:
            raise NotFound(f"prodotto '{name}' non trovato")
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
        names = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
        dd = [names.index(str(d)[:3].lower()) if str(d)[:3].lower() in names else int(d) for d in days or []]
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
        d = hygieia.save_routine(body, reason="creata dall'assistente", source="assistant")
        return {"saved": True, "name": d["name"], "cadence": d["cadence_label"],
                "steps": [s.get("label") or (s.get("product") or {}).get("name") for s in d["steps"]],
                "notes": [n["text"] for n in d["check"]]}

    def _routine_edit(routine: str = "", reason: str = "", add_step: str = "", position: int | None = None,
                      remove_step: str = "", step: str = "", step_times: int | None = None, step_per: str = "",
                      pause_days: int | None = None, amount: str = "", wait_minutes: int | None = None,
                      name: str = "", cadence_mode: str = "", times: int | None = None, per: str = "",
                      days: list | None = None, status: str = "", reminder: bool | None = None,
                      favorite: bool | None = None) -> dict:
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
                return {"error": f"passo '{remove_step}' non trovato in {r['name']}"}
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
                return {"error": f"passo '{step}' non trovato in {r['name']}"}
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
        if not body:
            return {"error": "nessuna modifica indicata"}
        d = hygieia.save_routine(body, id=r["id"], reason=reason or "modificata dall'assistente", source="assistant")
        return {"saved": True, "name": d["name"], "version": d.get("version"), "cadence": d["cadence_label"],
                "steps": [(s.get("label") or (s.get("product") or {}).get("name"))
                          + (f" [{s['cadence_label']}]" if s.get("cadence_label") else "")
                          + (f" [pausa fino al {s['paused_until']}]" if s.get("paused_until") else "") for s in d["steps"]],
                "notes": [n["text"] for n in d["check"]], "undo": "selfcare_undo_routine"}

    def _undo_routine(routine: str = "") -> dict:
        d = hygieia.undo_routine(_need_routine(routine)["id"], source="assistant")
        return {"restored": d["name"], "version": d.get("version")}

    def _journal_add(area: str = "", scores: dict | None = None, note: str = "", tags: list | None = None,
                     date: str = "") -> dict:
        rows = hygieia.journal_add({"date": date or None, "entries": [{"area": area, "scores": scores or {}, "note": note,
                                                                      "tags": tags or []}]}, source="assistant")
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
        MCPTool(name="selfcare_overview", description="Self care di Marko: routine (con passi e frequenza), prodotti in "
                "uso, avvisi (scadenze, da ricomprare) e cosa resta oggi. Usalo per primo per qualsiasi domanda su "
                "skincare, capelli, corpo, cosmetici.", parameters={"type": "object", "properties": {}},
                handler=_t(_overview), title="✨ Self care", path=f"{API}/overview", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="selfcare_today", description="Cosa fare oggi (o in 'date'): routine con stato (due = da fare, "
                "suggested = consigliata, blocked = non oggi e perché, done), passi da fare stasera, passi esclusi oggi "
                "(es. retinolo vs acido).", parameters={"type": "object", "properties": {"date": S}},
                handler=_t(_today), title="✨ Self care oggi", path=f"{API}/today", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="selfcare_log", description="Registra: routine fatta (status done|partial|skipped, skipped_steps = "
                "passi saltati per nome) oppure uso extra di un prodotto (product, es. 'maschera'). date YYYY-MM-DD, "
                "default oggi.", parameters={"type": "object", "properties": {
                    "routine": S, "status": S, "skipped_steps": L, "product": S, "date": S, "note": S}},
                handler=_t(_log), title="✨ Segna self care", method="POST", path=f"{API}/log", clients=["telegram", "ui"],
                telegram_group=G),
        MCPTool(name="selfcare_products", description="Cerca i prodotti (query nome/marca, area viso|capelli|corpo…, "
                "status current (default) | all | in_use | stock | wishlist | finished, active es. retinolo).",
                parameters={"type": "object", "properties": {"query": S, "area": S, "status": S, "active": S, "category": S}},
                handler=_t(_products), title="✨ Prodotti self care", path=f"{API}/products", clients=["telegram", "ui"],
                telegram_group=G),
        MCPTool(name="selfcare_product_get", description="Dettaglio di un prodotto: utilizzi, scadenza, stima di quando "
                "finisce, routine che lo usano, storia, confezioni precedenti.",
                parameters={"type": "object", "properties": {"product": S}, "required": ["product"]},
                handler=_t(_product_get), title="✨ Prodotto", path=f"{API}/products/{{id}}", clients=["ui"],
                telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_product_add", description="Aggiungi un prodotto (es. 'ho comprato il siero X 30ml'). "
                "status in_use (aperto, default) | stock (chiuso) | wishlist. actives = slug (retinolo, niacinamide, "
                "aha_glicolico, bha_salicilico, vitamina_c…). category es. detergente, siero, crema, spf, shampoo.",
                parameters={"type": "object", "properties": {"name": S, "brand": S, "category": S, "areas": L, "actives": L,
                                                             "size": N, "unit": S, "price": N, "status": S, "pao_months": I,
                                                             "notes": S, "favorite": B}, "required": ["name"]},
                handler=_t(_product_add), title="✨ Aggiungi prodotto", method="POST", path=f"{API}/products",
                clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="selfcare_product_update", description="Aggiorna un prodotto: status in_use (aperto) | finished | "
                "discarded | paused | stock, level full|3/4|half|1/4|almost_empty, rating 1-5, verdict "
                "repurchase|maybe|never, repurchased=true se l'ha ricomprato (nuova confezione).",
                parameters={"type": "object", "properties": {"product": S, "status": S, "level": S, "rating": I, "verdict": S,
                                                             "favorite": B, "notes": S, "price": N, "opened_at": S,
                                                             "expires_at": S, "repurchased": B}, "required": ["product"]},
                handler=_t(_product_update), title="✨ Aggiorna prodotto", method="PUT", path=f"{API}/products/{{id}}",
                clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="selfcare_routines", description="Le routine con frequenza, stato di oggi e obiettivo (es. 1/2 sett.).",
                parameters={"type": "object", "properties": {}}, handler=_t(_routines), title="✨ Routine",
                path=f"{API}/routines", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="selfcare_routine_get", description="Una routine: passi in ordine con quantità, attese e frequenza "
                "propria, statistiche, storia delle versioni, avvisi di compatibilità.",
                parameters={"type": "object", "properties": {"routine": S}, "required": ["routine"]},
                handler=_t(_routine_get), title="✨ Routine", path=f"{API}/routines/{{id}}", clients=["ui"],
                telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_routine_create", description="Crea una routine. steps = nomi di prodotti (cercati "
                "nell'inventario) o descrizioni. cadence_mode daily | fixed_days (days lun..dom) | target (times per "
                "week|month, default) | as_needed. Solo dopo il sì dell'utente.",
                parameters={"type": "object", "properties": {"name": S, "slot": S, "areas": L, "steps": L, "cadence_mode": S,
                                                             "times": I, "per": S, "days": L, "reminder": B, "favorite": B},
                            "required": ["name"]},
                handler=_t(_routine_create), title="✨ Crea routine", method="POST", path=f"{API}/routines",
                clients=["ui"], telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_routine_edit", description="Modifica una routine (crea una nuova versione, annullabile): "
                "add_step (+position, amount, wait_minutes), remove_step, step + step_times/step_per (frequenza propria "
                "del passo, 0 = sempre) o pause_days (es. 'niente retinolo per una settimana' = step retinolo, "
                "pause_days 7; 0 = riprendi), cadence_mode/times/per/days della routine, status active|paused, "
                "reminder, favorite. reason = perché (finisce nella storia).",
                parameters={"type": "object", "properties": {
                    "routine": S, "reason": S, "add_step": S, "position": I, "remove_step": S, "step": S, "step_times": I,
                    "step_per": S, "pause_days": I, "amount": S, "wait_minutes": I, "name": S, "cadence_mode": S,
                    "times": I, "per": S, "days": L, "status": S, "reminder": B, "favorite": B}, "required": ["routine"]},
                handler=_t(_routine_edit), title="✨ Modifica routine", method="PUT", path=f"{API}/routines/{{id}}",
                clients=["ui"], telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_undo_routine", description="Annulla l'ultima modifica dei passi di una routine.",
                parameters={"type": "object", "properties": {"routine": S}, "required": ["routine"]},
                handler=_t(_undo_routine), title="✨ Annulla modifica routine", method="POST",
                path=f"{API}/routines/{{id}}/undo", clients=["ui"], telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_journal_add", description="Diario (se attivo): voti 1-5 per area, es. area viso scores "
                "{brufoli: 2, idratazione: 4}, capelli {caduta: 3}; note e tags (stress, sole, ciclo…).",
                parameters={"type": "object", "properties": {"area": S, "scores": O, "note": S, "tags": L, "date": S},
                            "required": ["area"]},
                handler=_t(_journal_add), title="✨ Diario self care", method="POST", path=f"{API}/journal", clients=["ui"],
                telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_stats", description="Statistiche: costanza per routine (streak, % periodi rispettati), "
                "prodotti più usati, spesa per mese.", parameters={"type": "object", "properties": {"days": I}},
                handler=_t(_stats), title="✨ Statistiche self care", path=f"{API}/stats", clients=["ui"],
                telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_timeline", description="Cosa è cambiato nel tempo: versioni delle routine, prodotti "
                "aperti/finiti/sostituiti, diario. since/until YYYY-MM-DD.",
                parameters={"type": "object", "properties": {"days": I, "since": S, "until": S}}, handler=_t(_timeline),
                title="✨ Storia self care", path=f"{API}/timeline", clients=["ui"], telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_period", description="Routine e prodotti in uso in una certa data (es. 'cosa usavo a marzo').",
                parameters={"type": "object", "properties": {"date": S}, "required": ["date"]}, handler=_t(_period),
                title="✨ Self care in una data", path=f"{API}/period", clients=["ui"], telegram_visible=False,
                telegram_group=G),
        MCPTool(name="selfcare_check", description="Compatibilità degli attivi (consiglio, mai blocco): di una routine, "
                "o di un prodotto / lista di attivi rispetto a quelli in uso.",
                parameters={"type": "object", "properties": {"routine": S, "product": S, "actives": L}},
                handler=_t(_check), title="✨ Compatibilità", path=f"{API}/check", clients=["ui"],
                telegram_visible=False, telegram_group=G),
        MCPTool(name="selfcare_shopping", description="Lista spesa self care: desideri, da ricomprare (sta finendo, "
                "finito in una routine), finiti col giudizio 'lo ricompro'.", parameters={"type": "object", "properties": {}},
                handler=_t(_shopping), title="✨ Lista spesa self care", path=f"{API}/shopping", clients=["telegram", "ui"],
                telegram_group=G),
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
    caps = {"mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": ["selfcare"],
            "context_endpoint": "/api/module/context"}
    try:
        caps.update(ui.capabilities(SERVICE_BASE_URL))
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

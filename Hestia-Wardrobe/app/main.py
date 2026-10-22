"""Hestia-Wardrobe — the wardrobe: pieces, accessories, outfits, "Indossato" marks, suggestions (domain ``wardrobe``).

SPEC docs/work/2026-10-17-modulo-guardaroba. Data in Archive (``/api/wardrobe-store`` + photos in ``/api/blobs``),
settings in Themis, reminders through the agenda (Chronos) and Hermes, UI as a plugin bundle (``ui/``),
assistant tools over MCP, AI photo description through Oracle only.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

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
from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase as llm_usecase
from hestia_common.plugin_client import PluginClient, page, quick_action, widget
from hestia_common.transfer import StoreSection, Transfer
from hestia_common.reminders import reminder_event, reminder_settings
from hestia_common.settings_client import SettingsClient, setting
from hestia_common.signals_client import Signals, signals_rule

from .core import domain
from .core.hub import Hub, HubError
from .core.photos import PhotoError
from .core.service import NotFound, Wardrobe
from .core.store import Store, StoreUnavailable

logger, log_buffer = setup_service_logging("hestia_wardrobe")

SERVICE_NAME = os.getenv("SERVICE_NAME", "wardrobe")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_wardrobe:19017")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "module")
SERVICE_TAGS = [t.strip().lower() for t in os.getenv("SERVICE_TAGS", "module,wardrobe,context").split(",") if t.strip()]
SERVICE_TOPOLOGY_TAGS = [t.strip().lower() for t in os.getenv(
    "SERVICE_TOPOLOGY_TAGS", "layer:domain,domain:wardrobe,status:alpha").split(",") if t.strip()]
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
UI_DIST = os.getenv("WARDROBE_UI_DIST", "/code/ui/dist")
TZ = os.getenv("TZ") or "Europe/Rome"
API = "/api/wardrobe"

# ── settings (Themis) ────────────────────────────────────────────────────────
settings = SettingsClient("wardrobe")
settings.declare([
    setting("wardrobe.forgotten_days", "Capo dimenticato dopo", "int", 180, group="Generale", min=14, max=1095, unit="giorni",
            help="Capi non indossati da più giorni di così finiscono tra i «dimenticati»."),
    setting("wardrobe.photo.max_mb", "Dimensione massima foto", "int", 10, group="Generale", min=1, max=15, unit="MB"),
    setting("wardrobe.suggest.count", "Outfit suggeriti", "int", 3, group="Suggerimenti", min=1, max=10),
    setting("wardrobe.suggest.exclude_recent_days", "Non riproporre per", "int", 4, group="Suggerimenti", min=0, max=30,
            unit="giorni", help="Un capo o un outfit segnato «Indossato» non viene riproposto per questi giorni."),
    setting("wardrobe.tracking.goal_times", "Obiettivo «Indossato»", "int", 0, group="Indossato", min=0, max=31,
            help="Quante volte vuoi segnare cosa indossi nel periodo. 0 = nessun obiettivo (segni solo quando ti va)."),
    setting("wardrobe.tracking.goal_per", "Periodo dell'obiettivo", "enum", "week", group="Indossato",
            options=[("day", "Al giorno"), ("week", "A settimana"), ("month", "Al mese")],
            depends_on={"key": "wardrobe.tracking.goal_times", "not_equals": 0}),
    *reminder_settings("wardrobe", help="Solo con un obiettivo, solo se sei indietro e oggi non hai segnato nulla. Uno "
                                        "alla volta; l'orario si cambia nell'agenda (Promemoria guardaroba)."),
    setting("wardrobe.review.enabled", "Revisione mensile", "bool", False, group="Notifiche",
            help="Una volta al mese: capi dimenticati, da riparare, in lavanderia da tanto, outfit da rivedere."),
]).follow_personal()                                       # week start, currency: personal settings shared by every module

hub = Hub(HUB_API_URL)
store = Store(hub)
wardrobe = Wardrobe(store, hub, settings.get, TZ)
agenda = AgendaClient("wardrobe", HUB_API_URL)
# Reflection signals (forgotten pieces, laundry backlog, to repair + weekly worn count) → Archive signals-store.
# evaluate goes through the module global so tests can swap ``wardrobe``.
signals = Signals("wardrobe", "wardrobe", evaluate=lambda: wardrobe.signals(), hub_api_url=HUB_API_URL)

app = FastAPI(title="Hestia-Wardrobe", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(domain.Invalid)
async def _invalid(_: Request, exc: domain.Invalid):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(PhotoError)
async def _photo(_: Request, exc: PhotoError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(StoreUnavailable)
async def _store_down(_: Request, exc: StoreUnavailable):
    return JSONResponse(status_code=503, content={"detail": "archivio non raggiungibile, riprova tra poco"})


@app.exception_handler(HubError)
async def _hub_error(_: Request, exc: HubError):
    logger.warning("[🔄] event=wardrobe_hub_call_failed status=%s", exc.status)
    return JSONResponse(status_code=502, content={"detail": "servizio non raggiungibile, riprova tra poco"})


def _refresh() -> None:
    store.refresh()


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_wardrobe", "version": SERVICE_VERSION, "mirror_loaded": store.loaded,
            "rows": len(store.rows), "cursor": store.cursor}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    logs = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_wardrobe", "count": len(logs), "logs": logs}


# ── meta & vocabularies ──────────────────────────────────────────────────────
@app.get(f"{API}/meta")
def meta():
    _refresh()
    return wardrobe.meta()


@app.get(f"{API}/vocabularies")
def vocabularies():
    return wardrobe.vocabularies()


@app.put(f"{API}/vocabularies/{{name}}")
def vocabulary_save(name: str, body: dict = Body(...)):
    return {"name": name, "values": wardrobe.set_vocabulary(name, body.get("values") or [])}


# ── pieces ───────────────────────────────────────────────────────────────────
@app.get(f"{API}/pieces")
def pieces(kind: str = "", category: str = "", status: str = "", season: str = "", style: str = "", occasion: str = "",
           color: str = "", q: str = "", favorite: bool | None = None, not_worn_days: int | None = None,
           sort: str = "recent", include_archived: bool = False, limit: int = 500, offset: int = 0):
    _refresh()
    return wardrobe.pieces(kind=kind, category=category, status=status, season=season, style=style, occasion=occasion,
                           color=color, q=q, favorite=favorite, not_worn_days=not_worn_days, sort=sort,
                           include_archived=include_archived, limit=limit, offset=offset)


@app.post(f"{API}/pieces")
def piece_create(body: dict = Body(...)):
    upload = body.pop("photo", None)
    created = wardrobe.save_piece(body)
    if upload:
        created = wardrobe.add_photo("piece", created["id"], upload, cover=True)["item"]
    return created


@app.post(f"{API}/pieces/bulk")
def pieces_bulk(body: dict = Body(...)):
    out = wardrobe.bulk([str(i) for i in body.get("ids") or []], body.get("changes") or {})
    signals.changed()
    return out


@app.get(f"{API}/pieces/{{id}}")
def piece_get(id: str):
    _refresh()
    return wardrobe.piece_detail(id)


@app.patch(f"{API}/pieces/{{id}}")
def piece_update(id: str, body: dict = Body(...)):
    out = wardrobe.save_piece(body, id, partial=True)
    signals.changed()
    return out


@app.delete(f"{API}/pieces/{{id}}")
def piece_delete(id: str, hard: bool = False):
    out = wardrobe.delete_piece(id, hard=hard)
    signals.changed()
    return out


@app.post(f"{API}/pieces/{{id}}/photos")
def piece_photo_add(id: str, body: dict = Body(...)):
    return wardrobe.add_photo("piece", id, body.get("photo") or body, cover=bool(body.get("cover")))


@app.delete(f"{API}/pieces/{{id}}/photos/{{photo_id}}")
def piece_photo_remove(id: str, photo_id: str):
    return wardrobe.remove_photo("piece", id, photo_id)


@app.post(f"{API}/pieces/{{id}}/photos/{{photo_id}}/cover")
def piece_photo_cover(id: str, photo_id: str):
    return wardrobe.set_cover("piece", id, photo_id)


@app.get(f"{API}/files/{{photo_id}}")
def photo_file(photo_id: str, size: str = "thumb"):
    """Image as ``{mime, data_b64}`` (plugin contract: the WebUI serves the bytes, cached by immutable id)."""
    return wardrobe.photo_file(photo_id, size)


# ── outfits ──────────────────────────────────────────────────────────────────
@app.get(f"{API}/outfits")
def outfits(q: str = "", season: str = "", occasion: str = "", style: str = "", favorite: bool | None = None,
            include_archived: bool = False, sort: str = "recent", limit: int = 300, offset: int = 0):
    _refresh()
    return wardrobe.outfits(q=q, season=season, occasion=occasion, style=style, favorite=favorite,
                            include_archived=include_archived, sort=sort, limit=limit, offset=offset)


@app.post(f"{API}/outfits")
def outfit_create(body: dict = Body(...)):
    return wardrobe.save_outfit(body)


@app.get(f"{API}/outfits/{{id}}")
def outfit_get(id: str):
    _refresh()
    return wardrobe.outfit_detail(id)


@app.patch(f"{API}/outfits/{{id}}")
def outfit_update(id: str, body: dict = Body(...)):
    return wardrobe.save_outfit(body, id, partial=True)


@app.delete(f"{API}/outfits/{{id}}")
def outfit_delete(id: str, hard: bool = False):
    return wardrobe.delete_outfit(id, hard=hard)


@app.post(f"{API}/outfits/{{id}}/photos")
def outfit_photo_add(id: str, body: dict = Body(...)):
    return wardrobe.add_photo("outfit", id, body.get("photo") or body, cover=bool(body.get("cover")))


@app.delete(f"{API}/outfits/{{id}}/photos/{{photo_id}}")
def outfit_photo_remove(id: str, photo_id: str):
    return wardrobe.remove_photo("outfit", id, photo_id)


@app.post(f"{API}/outfits/{{id}}/worn")
def outfit_worn(id: str, body: dict = Body(default={})):
    out = wardrobe.mark_worn({**(body or {}), "outfit_id": id})
    signals.changed()
    return out


@app.delete(f"{API}/outfits/{{id}}/worn/today")
def outfit_unworn(id: str, date: str = ""):
    out = wardrobe.unmark_outfit(id, date)
    signals.changed()
    return out


# ── "Indossato" marks ────────────────────────────────────────────────────────
@app.get(f"{API}/wears")
def wears(date_from: str = "", date_to: str = "", limit: int = 200):
    _refresh()
    return wardrobe.wears(date_from=date_from, date_to=date_to, limit=limit)


@app.post(f"{API}/wears")
def wear_create(body: dict = Body(...)):
    out = wardrobe.mark_worn(body)
    signals.changed()
    return out


@app.delete(f"{API}/wears/{{id}}")
def wear_delete(id: str):
    out = wardrobe.delete_wear(id)
    signals.changed()
    return out


# ── suggestions & stats ──────────────────────────────────────────────────────
@app.post(f"{API}/suggest")
def suggest(body: dict = Body(default={})):
    _refresh()
    b = body or {}
    temp = b.get("temp_c")
    return wardrobe.suggest(day=b.get("date") or "", occasion=b.get("occasion") or "", styles=b.get("styles"),
                            temp_c=float(temp) if temp not in (None, "") else None, rain=bool(b.get("rain")),
                            count=b.get("count"), exclude_recent_days=b.get("exclude_recent_days"))


@app.post(f"{API}/suggest/save")
def suggest_save(body: dict = Body(...)):
    return wardrobe.save_suggestion(body.get("slots") or [], body.get("name") or "", body.get("source") or "user")


@app.get(f"{API}/stats")
def stats():
    _refresh()
    return wardrobe.stats()


@app.get(f"{API}/summary")
def summary():
    _refresh()
    return wardrobe.summary()


@app.get("/api/module/context")
def module_context(budget: int = 400, topic: str = ""):
    """Assistant context contract (SPEC §6.2): a short caveman line Oracle may include. ``topic`` = a signal key
    (``forgotten``, ``laundry_backlog``, ``to_repair``) → the detail behind it; unknown topic → the normal line."""
    _refresh()
    return wardrobe.context(budget, topic)


@app.post(f"{API}/signals/run")
def signals_run():
    """Agenda job ``wardrobe.signals``: re-evaluate the reflection signals and the weekly worn count, sync to Archive."""
    _refresh()
    return signals.run()


# ── collections (capsule, packing lists, shopping) ───────────────────────────
@app.get(f"{API}/collections")
def collections(type: str = "", include_archived: bool = False):
    _refresh()
    return wardrobe.collections(type=type, include_archived=include_archived)


@app.post(f"{API}/collections")
def collection_create(body: dict = Body(...)):
    return wardrobe.save_collection(body)


@app.post(f"{API}/collections/packing")
def collection_packing(body: dict = Body(default={})):
    b = body or {}
    temp = b.get("temp_c")
    return wardrobe.packing(name=b.get("name") or "", date_from=b.get("from") or b.get("date_from") or "",
                            date_to=b.get("to") or b.get("date_to") or "", place=b.get("place") or "",
                            occasion=b.get("occasion") or "", temp_c=float(temp) if temp not in (None, "") else None,
                            rain=bool(b.get("rain")))


@app.get(f"{API}/collections/{{id}}")
def collection_get(id: str):
    return wardrobe.collection_detail(id)


@app.patch(f"{API}/collections/{{id}}")
def collection_update(id: str, body: dict = Body(...)):
    return wardrobe.save_collection(body, id, partial=True)


@app.post(f"{API}/collections/{{id}}/check")
def collection_check(id: str, body: dict = Body(...)):
    return wardrobe.toggle_check(id, str(body.get("item_id") or ""), body.get("checked"))


@app.delete(f"{API}/collections/{{id}}")
def collection_delete(id: str):
    return wardrobe.delete_collection(id)


# ── AI help, export / import ─────────────────────────────────────────────────
@app.post(f"{API}/describe-photo")
def describe_photo(body: dict = Body(...)):
    return wardrobe.describe_photo(body.get("photo") or body)


@app.get(f"{API}/export")
def export():
    return wardrobe.export()


@app.post(f"{API}/import")
def import_json(body: dict = Body(...)):
    out = wardrobe.import_json(str(body.get("text") or ""))
    signals.changed()
    return out


# ── quick actions (WebUI Home) ───────────────────────────────────────────────
@app.get(f"{API}/quick/outfits")
def quick_outfits():
    _refresh()
    return wardrobe.quick_chips()


@app.post(f"{API}/quick/{{id}}")
def quick_mark(id: str, body: dict = Body(default={})):
    b = body or {}
    out = wardrobe.quick_mark(id, b.get("date"), b.get("note") or "", b.get("source") or "webui")
    signals.changed()
    return out


@app.delete(f"{API}/quick/{{id}}")
def quick_undo(id: str, date: str = ""):
    out = wardrobe.quick_undo(id, date)
    signals.changed()
    return out


# ── notifications through Hermes (agenda jobs; both off by default) ──────────
def _notify(key: str, title: str, text: str, actions: list[dict], *, replaces: bool, page: str = "") -> None:
    body = reminder_event(module="wardrobe", domain="wardrobe", key=key, title=title, text=text, actions=actions,
                          page=page)
    if not replaces:                                   # a one-off question (delete), not a reminder thread
        body["payload"].pop("replaces", None)
    hub.ok("hermes", "POST", "api/events/ingest", body=body, timeout=8)


@app.post(f"{API}/reminder/check")
def reminder_check():
    _refresh()
    decision = wardrobe.reminder_decision()
    if not decision.get("send"):
        logger.info("event=wardrobe_reminder_skipped why=%s", decision.get("why"))
        return decision
    goal = decision["goal"]
    actions = [{"id": f"wear-{i}", "label": c["label"], "text": f"👕 {c['label']}", "style": "primary" if i == 0 else None,
                "service": "wardrobe", "method": "POST", "path": f"{API}/quick/{c['id']}", "body": {"source": "reminder"},
                "resolves": True} for i, c in enumerate(decision.get("chips") or [])]
    actions.append({"id": "skip", "label": "Salta", "text": "⏭ Salta", "service": "wardrobe", "method": "POST",
                    "path": f"{API}/reminder/skip", "body": {}})
    try:
        _notify("wardrobe.reminder", "Guardaroba", f"👕 Cosa indossi oggi? · {goal['hint']}", actions, replaces=True,
                page="outfit")
        wardrobe.mark_reminder_sent()
    except Exception as exc:
        logger.warning("[🔄] event=wardrobe_reminder_emit_failed error=%s fallback=next_check", exc)
        return {"send": False, "why": "hermes_unreachable"}
    logger.info("event=wardrobe_reminder_sent hint=%s", goal["hint"])
    return {"send": True}


@app.post(f"{API}/reminder/skip")
def reminder_skip(body: dict = Body(default={})):
    """«Non oggi» on the reminder, «Tieni» on a delete question: nothing to do, Hermes closes the card."""
    return {"ok": True, "message": str((body or {}).get("message") or "Ok, niente per oggi")[:120]}


@app.post(f"{API}/review/run")
def review_run():
    if not settings.get("wardrobe.review.enabled", False):
        return {"send": False, "why": "disabled"}
    _refresh()
    s = wardrobe.stats()
    repair = [p["name"] for p in wardrobe.pieces(status="to_repair")["items"]]
    laundry = [p["name"] for p in wardrobe.pieces(status="laundry")["items"]
               if str(p.get("updated_at") or "")[:10] < (wardrobe.today().isoformat()[:8] + "01")]
    review = [o["name"] for o in wardrobe.outfits(limit=500)["items"] if not o["complete"]]
    lines = []
    if s["forgotten"]:
        lines.append(f"• Dimenticati: {len(s['forgotten'])} (es. {', '.join(f['name'] for f in s['forgotten'][:3])})")
    if repair:
        lines.append(f"• Da riparare: {', '.join(repair[:5])}")
    if laundry:
        lines.append(f"• In lavanderia da tanto: {', '.join(laundry[:5])}")
    if review:
        lines.append(f"• Outfit da rivedere: {', '.join(review[:5])}")
    if not lines:
        return {"send": False, "why": "nothing_to_say"}
    try:
        _notify("wardrobe.review", "Guardaroba del mese", "👕 Revisione del guardaroba\n" + "\n".join(lines), [],
                replaces=True, page="statistiche")
    except Exception as exc:
        logger.warning("[🔄] event=wardrobe_review_emit_failed error=%s fallback=next_month", exc)
        return {"send": False, "why": "hermes_unreachable"}
    return {"send": True, "lines": lines}


def _agenda_rules() -> list[dict]:
    return [job_rule("wardrobe.reminder", "Promemoria guardaroba", service="wardrobe", path=f"{API}/reminder/check",
                     recurrence="FREQ=DAILY", start_at="2026-01-01T08:30:00", tz=TZ,
                     description="Chiede cosa indossi solo se hai un obiettivo «Indossato», sei indietro e oggi non hai "
                                 "segnato nulla. Spento nelle impostazioni = non invia niente (default)."),
            job_rule("wardrobe.review", "Revisione mensile del guardaroba", service="wardrobe", path=f"{API}/review/run",
                     recurrence="FREQ=MONTHLY;BYDAY=1SU", start_at="2026-01-04T10:00:00", tz=TZ,
                     description="Capi dimenticati, da riparare, in lavanderia da tanto, outfit da rivedere. "
                                 "Solo se la revisione mensile è accesa nelle impostazioni."),
            signals_rule("wardrobe", "Guardaroba", path=f"{API}/signals/run", tz=TZ)]


# ── plugin (UI bundle) ───────────────────────────────────────────────────────
ui = PluginClient("wardrobe", title="Guardaroba", icon="shirt", color="purple",
                  description="Capi, accessori, outfit e cosa mettersi.", dist=UI_DIST, version=SERVICE_VERSION)
ui.webui(
    entry="wardrobe.js", api_prefix=f"{API}/",
    pages=[page("capi", "Guardaroba", element="wardrobe-pieces", icon="shirt", order=50,
                help="Tutti i tuoi capi con foto, filtri e ricerca."),
           page("capi/:id", "Capo", element="wardrobe-piece", detail=True, parent="capi"),
           page("accessori", "Accessori", element="wardrobe-accessories", icon="tag", order=51, parent="capi"),
           page("outfit", "Outfit", element="wardrobe-outfits", icon="grid", order=52, parent="capi"),
           page("outfit/:id", "Outfit", element="wardrobe-outfit", detail=True, parent="capi"),
           page("cosa-mi-metto", "Cosa mi metto", element="wardrobe-suggest", icon="sparkle", order=53, parent="capi"),
           page("statistiche", "Statistiche", element="wardrobe-stats", icon="chart", order=54, parent="capi"),
           page("liste", "Valigie e liste", element="wardrobe-collections", icon="list", order=55, parent="capi"),
           page("liste/:id", "Lista", element="wardrobe-collection", detail=True, parent="capi"),
           page("vocabolari", "Vocabolari", element="wardrobe-vocab", icon="settings", order=56, parent="capi")],
    widgets=[widget("oggi", "Oggi indosso", element="wardrobe-today-widget", sizes=["m", "l"], auto=True,
                    open_page="outfit", icon="shirt",
                    params={"occasion": {"type": "string", "label": "Occasione (es. ufficio)"}}),
             widget("suggerito", "Outfit di oggi", element="wardrobe-suggest-widget", sizes=["m", "l"],
                    open_page="cosa-mi-metto", icon="sparkle",
                    params={"occasion": {"type": "string", "label": "Occasione"}}),
             widget("lavanderia", "In lavanderia", element="wardrobe-laundry-widget", sizes=["s", "m"], open_page="capi",
                    icon="refresh"),
             widget("dimenticati", "Capi dimenticati", element="wardrobe-forgotten-widget", sizes=["m", "l"], auto=True,
                    open_page="statistiche", icon="clock"),
             widget("numeri", "Guardaroba in numeri", element="wardrobe-kpi-widget", sizes=["s", "m"], auto=True,
                    open_page="statistiche", icon="chart"),
             widget("ultimi", "Ultimi outfit", element="wardrobe-recent-widget", sizes=["m", "l"], open_page="outfit",
                    icon="clock")],
    quick_actions=[
        quick_action("indossato", "Outfit indossato", "POST", f"{API}/quick/{{id}}", icon="shirt", group="Guardaroba",
                     source=f"{API}/quick/outfits", undo={"method": "DELETE", "path": f"{API}/quick/{{id}}"},
                     favorite=True, order=50),
    ],
)
app.include_router(ui.router())
app.include_router(settings.router())

# ── export / import (hestia_common.transfer; reminder/alert rows are runtime state) ─────────────────────
transfer = Transfer("wardrobe", hub, sections=[
    StoreSection("capi", "Capi", store, ["piece"], icon="shirt",
                 subtitle=lambda r: " · ".join(x for x in (r["data"].get("category"), r["data"].get("brand")) if x),
                 depends_on=["vocabolari", "foto"]),
    StoreSection("outfit", "Outfit", store, ["outfit"], icon="sparkle", depends_on=["capi", "foto"]),
    StoreSection("indossati", "Indossati", store, ["wear"], icon="history",
                 title=lambda r: f"Indossato il {r['data'].get('date')}", depends_on=["capi", "outfit"]),
    StoreSection("liste", "Liste", store, ["collection"], icon="list", depends_on=["capi", "outfit"]),
    StoreSection("vocabolari", "Vocabolari", store, ["taxonomy"], icon="tag", title=lambda r: r["id"]),
    StoreSection("foto", "Foto", store, ["photo"], icon="camera", file_fields=["original", "medium", "thumb"],
                 title=lambda r: r["data"].get("name") or "Foto", subtitle=lambda r: r["data"].get("owner") or ""),
])
app.include_router(transfer.router())


# ── MCP tools (domain wardrobe; Oracle calls them, the logic stays here) ─────
def _t(fn):
    def run(**kw):
        try:
            store.refresh()
            return fn(**{k: v for k, v in kw.items() if v is not None})
        except (domain.Invalid, NotFound, PhotoError) as exc:
            return {"error": str(exc)}
    return run


def _brief_piece(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"], "kind": p["kind"], "category": p.get("subcategory_label") or p.get("category_label"),
            "colors": [c["name"] for c in p.get("colors") or []], "seasons": p.get("seasons"), "styles": p.get("styles"),
            "status": p.get("status_label"), "last_worn": p.get("last_worn"), "favorite": p.get("favorite") or None}


try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router, mount_missing_rest_routes

    def _search(query: str = "", kind: str = "", category: str = "", season: str = "", status: str = "",
                color: str = "", not_worn_days: int | None = None, limit: int = 15) -> dict:
        r = wardrobe.pieces(q=query, kind=kind, category=category, season=season, status=status, color=color,
                            not_worn_days=not_worn_days, limit=max(1, min(int(limit), 40)))
        return {"total": r["total"], "items": [_brief_piece(p) for p in r["items"]]}

    def _piece(piece: str = "") -> dict:
        p = wardrobe.find_piece(piece)
        if not p:
            return {"error": f"capo '{piece}' non trovato"}
        d = wardrobe.piece_detail(p["id"])
        return {**_brief_piece(d), "brand": d.get("brand"), "size": d.get("size"), "materials": d.get("materials"),
                "purchase": d.get("purchase"), "wear_count": d.get("wear_count"), "cost_per_wear": d.get("cost_per_wear"),
                "outfits": [o["name"] for o in d["outfits"]], "notes": d.get("notes")}

    def _add(name: str = "", category: str = "", colors: list | None = None, brand: str = "", size: str = "",
             seasons: list | None = None, styles: list | None = None, materials: list | None = None, price: float | None = None,
             purchase_date: str = "", store_name: str = "", notes: str = "", status: str = "active",
             warmth: int | None = None, formality: int | None = None) -> dict:
        p = wardrobe.save_piece({"name": name, "category": category, "colors": colors or [], "brand": brand, "size": size,
                                 "seasons": seasons, "styles": styles, "materials": materials or [], "notes": notes,
                                 "status": status, "warmth": warmth, "formality": formality,
                                 "purchase": {"price": price, "date": purchase_date or None, "store": store_name}})
        return {"saved": True, **_brief_piece(p)}

    def _edit(piece: str = "", changes: dict | None = None, status: str = "", favorite: bool | None = None,
              location: str = "") -> dict:
        p = wardrobe.find_piece(piece)
        if not p:
            return {"error": f"capo '{piece}' non trovato"}
        upd = {k: v for k, v in (changes or {}).items() if k not in ("id", "photos")}
        if status:
            upd["status"] = status
        if favorite is not None:
            upd["favorite"] = favorite
        if location:
            upd["location"] = location
        d = wardrobe.save_piece(upd, p["id"], partial=True)
        signals.changed()
        return {"saved": True, **_brief_piece(d)}

    def _outfits(query: str = "", season: str = "", occasion: str = "", favorite: bool | None = None, limit: int = 15) -> dict:
        r = wardrobe.outfits(q=query, season=season, occasion=occasion, favorite=favorite, limit=max(1, min(int(limit), 40)))
        return {"total": r["total"], "items": [{"id": o["id"], "name": o["name"], "pieces": [x["name"] for x in o["pieces"]],
                                                "occasions": o.get("occasions"), "seasons": o.get("seasons"),
                                                "favorite": o.get("favorite") or None, "last_worn": o.get("last_worn"),
                                                "available": o["available"], "complete": o["complete"]} for o in r["items"]]}

    def _create_outfit(name: str = "", pieces: list | None = None, occasions: list | None = None,
                       styles: list | None = None, favorite: bool = False) -> dict:
        ids, missing = [], []
        for text in pieces or []:
            p = wardrobe.find_piece(str(text))
            (ids.append(p["id"]) if p else missing.append(text))
        if missing:
            return {"error": f"capi non trovati: {', '.join(map(str, missing))}"}
        o = wardrobe.save_outfit({"name": name, "piece_ids": ids, "occasions": occasions, "styles": styles,
                                  "favorite": favorite, "source": "assistant"})
        return {"saved": True, "id": o["id"], "name": o["name"], "pieces": [x["name"] for x in o["pieces"]]}

    def _suggest(occasion: str = "", temp_c: float | None = None, rain: bool = False, date: str = "",
                 styles: list | None = None, count: int | None = None) -> dict:
        r = wardrobe.suggest(day=date, occasion=occasion, temp_c=temp_c, rain=rain, styles=styles, count=count)
        return {"date": r["date"], "season": r["season"], "hint": r.get("hint"),
                "items": [{"outfit_id": i.get("outfit_id"), "saved": i["saved"], "name": i["name"],
                           "pieces": [f"{x['name']} ({domain.SLOTS[x['slot']].lower()})" for x in i["pieces"]],
                           "piece_ids": [x["id"] for x in i["pieces"]], "why": i["reasons"]} for i in r["items"]]}

    def _worn(outfit: str = "", pieces: list | None = None, date: str = "", note: str = "") -> dict:
        body = {"date": date or None, "note": note, "source": "assistant"}
        if outfit:
            o = wardrobe.find_outfit(outfit)
            if not o:
                return {"error": f"outfit '{outfit}' non trovato"}
            body["outfit_id"] = o["id"]
        ids = []
        for text in pieces or []:
            p = wardrobe.find_piece(str(text))
            if not p:
                return {"error": f"capo '{text}' non trovato"}
            ids.append(p["id"])
        if ids:
            body["piece_ids"] = ids
        w = wardrobe.mark_worn(body)
        signals.changed()
        return {"saved": True, "date": w["date"], "label": w["label"], "goal": wardrobe.goal_progress()}

    def _stats() -> dict:
        s = wardrobe.stats()
        return {"totals": s["totals"], "by_category": s["by_category"][:10], "by_color": s["by_color"][:8],
                "by_season": s["by_season"], "forgotten": [f["name"] for f in s["forgotten"][:15]], "gaps": s["gaps"],
                "usage": {k: s["usage"][k] for k in ("has_marks", "most_worn", "never_marked", "cost_per_wear")}}

    def _summary() -> dict:
        return wardrobe.summary()

    def _packing(place: str = "", date_from: str = "", date_to: str = "", occasion: str = "", temp_c: float | None = None,
                 rain: bool = False) -> dict:
        c = wardrobe.packing(place=place, date_from=date_from, date_to=date_to, occasion=occasion, temp_c=temp_c, rain=rain)
        return {"saved": True, "id": c["id"], "name": c["name"], "pieces": [p["name"] for p in c["pieces"]],
                "outfits": [o["name"] for o in c["outfits"]]}

    def _delete(piece: str = "", outfit: str = "") -> dict:
        """Never deletes by itself: asks the user through Hermes (button), the button does the delete."""
        target = wardrobe.find_piece(piece) if piece else wardrobe.find_outfit(outfit) if outfit else None
        if not target:
            return {"error": "indica il capo o l'outfit da eliminare"}
        kind = "pieces" if piece else "outfits"
        label = "il capo" if piece else "l'outfit"
        try:
            _notify(f"wardrobe.delete.{target['id']}", "Guardaroba", f"🗑 Elimino {label} «{target['name']}»?",
                    [{"id": "delete", "label": "Elimina", "text": "🗑 Elimina", "style": "danger", "service": "wardrobe",
                      "method": "DELETE", "path": f"{API}/{kind}/{target['id']}?hard=true", "body": {}, "resolves": True},
                     {"id": "archive", "label": "Archivia", "text": "📦 Solo archivia", "service": "wardrobe",
                      "method": "DELETE", "path": f"{API}/{kind}/{target['id']}", "body": {}, "resolves": True},
                     {"id": "keep", "label": "Tieni", "text": "Tieni", "service": "wardrobe", "method": "POST",
                      "path": f"{API}/reminder/skip", "body": {"message": "Tenuto"}, "resolves": True}], replaces=False)
        except Exception as exc:
            return {"error": f"non riesco a chiedere conferma ora ({exc}); usa la pagina Guardaroba"}
        return {"asked": True, "message": f"Ho chiesto conferma per eliminare {label} «{target['name']}»"}

    S = {"type": "string"}
    I = {"type": "integer"}
    N = {"type": "number"}
    B = {"type": "boolean"}
    L = {"type": "array", "items": {"type": "string"}}
    G = "guardaroba"
    _tools = [
        MCPTool(name="wardrobe_summary", description="Guardaroba a colpo d'occhio: quanti capi/outfit, stile, in "
                "lavanderia, dimenticati, ultimo outfit indossato, obiettivo. Usalo prima di altro per domande sul "
                "guardaroba o sui vestiti.", parameters={"type": "object", "properties": {}}, handler=_t(_summary),
                title="👕 Riepilogo guardaroba", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_search", description="Cerca capi, scarpe e accessori che possiedo (testo libero: nome, "
                "colore, materiale, marca; filtri kind garment|shoes|accessory, season spring|summer|autumn|winter, status "
                "active|laundry|lent|to_repair|to_donate|wishlist, not_worn_days).",
                parameters={"type": "object", "properties": {"query": S, "kind": S, "category": S, "season": S, "status": S,
                                                             "color": S, "not_worn_days": I, "limit": I}},
                handler=_t(_search), title="👕 Cerca nel guardaroba", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_piece", description="Dettaglio di un capo (per nome o id): taglia, materiali, acquisto, "
                "outfit in cui è, quante volte segnato indossato.", parameters={"type": "object", "properties": {"piece": S},
                                                                                "required": ["piece"]},
                handler=_t(_piece), title="👕 Dettaglio capo", clients=["ui"], telegram_visible=False, telegram_group=G),
        MCPTool(name="wardrobe_add", description="Aggiungi un capo che l'utente dice di avere/aver comprato. "
                "category: chiave o nome (camicia, jeans, sneakers, giacca, orologio…). colors: nomi (blu navy, bianco). "
                "warmth/formality 1-5 se li sai.",
                parameters={"type": "object", "properties": {"name": S, "category": S, "colors": L, "brand": S, "size": S,
                                                             "seasons": L, "styles": L, "materials": L, "price": N,
                                                             "purchase_date": S, "store_name": S, "notes": S, "status": S,
                                                             "warmth": I, "formality": I}, "required": ["name", "category"]},
                handler=_t(_add), title="👕 Aggiungi capo", method="POST", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_update", description="Modifica un capo: status (laundry = in lavanderia, active = di "
                "nuovo nell'armadio, lent, to_repair, to_donate, donated), favorite, location o altri campi in changes.",
                parameters={"type": "object", "properties": {"piece": S, "status": S, "favorite": B, "location": S,
                                                             "changes": {"type": "object"}}, "required": ["piece"]},
                handler=_t(_edit), title="👕 Modifica capo", method="PATCH", clients=["ui"], telegram_visible=False,
                telegram_group=G),
        MCPTool(name="wardrobe_outfits", description="I miei outfit salvati (filtri: testo, stagione, occasione, preferiti).",
                parameters={"type": "object", "properties": {"query": S, "season": S, "occasion": S, "favorite": B,
                                                             "limit": I}},
                handler=_t(_outfits), title="👕 Outfit", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_create_outfit", description="Salva un outfit dai capi (nomi o id). Usalo quando l'utente "
                "chiede di salvare una combinazione o ne approva una suggerita.",
                parameters={"type": "object", "properties": {"name": S, "pieces": L, "occasions": L, "styles": L,
                                                             "favorite": B}, "required": ["pieces"]},
                handler=_t(_create_outfit), title="👕 Crea outfit", method="POST", clients=["ui"], telegram_visible=False,
                telegram_group=G),
        MCPTool(name="wardrobe_suggest", description="«Cosa mi metto»: outfit dai capi disponibili (non in "
                "lavanderia, giusta stagione e temperatura, non messi di recente) con i motivi. occasion: work, office, "
                "evening, date, travel, home, sport, ceremony, weekend, party. Aggiungi tu gusto e spiegazione.",
                parameters={"type": "object", "properties": {"occasion": S, "temp_c": N, "rain": B, "date": S,
                                                             "styles": L, "count": I}},
                handler=_t(_suggest), title="👕 Cosa mi metto", method="POST", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_log_worn", description="Segna cosa ho indossato (outfit per nome, oppure capi), "
                "default oggi. Facoltativo: l'utente lo fa solo quando vuole.",
                parameters={"type": "object", "properties": {"outfit": S, "pieces": L, "date": S, "note": S}},
                handler=_t(_worn), title="👕 Indossato", method="POST", clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_stats", description="Statistiche: composizione per categoria/colore/stagione, "
                "valore, capi dimenticati, lacune; uso (più messi, costo per utilizzo) solo come indicazione.",
                parameters={"type": "object", "properties": {}}, handler=_t(_stats), title="👕 Statistiche guardaroba",
                clients=["telegram", "ui"], telegram_group=G),
        MCPTool(name="wardrobe_packing", description="Prepara una lista valigia per un viaggio (date YYYY-MM-DD, luogo, "
                "occasione, temperatura prevista): un outfit al giorno dai capi disponibili.",
                parameters={"type": "object", "properties": {"place": S, "date_from": S, "date_to": S, "occasion": S,
                                                             "temp_c": N, "rain": B}, "required": ["date_from"]},
                handler=_t(_packing), title="👕 Valigia", method="POST", clients=["ui"], telegram_visible=False,
                telegram_group=G),
        MCPTool(name="wardrobe_delete", description="Elimina un capo o un outfit: NON elimina subito, manda all'utente "
                "una richiesta di conferma con i pulsanti Elimina / Archivia / Tieni.",
                parameters={"type": "object", "properties": {"piece": S, "outfit": S}},
                handler=_t(_delete), title="👕 Elimina", method="POST", clients=["ui"], telegram_visible=False,
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
                        kw.pop(k)
                elif typ == "boolean":
                    kw[k] = v.lower() in ("1", "true", "si", "sì", "yes")
                elif typ == "array":
                    kw[k] = [x.strip() for x in v.split(",") if x.strip()]
            return inner(**{k: v for k, v in kw.items() if k in props})
        return run

    for _tool in _tools:
        _tool.path = f"{API}/tools/{_tool.name.removeprefix('guardaroba_')}"
        _tool.method = "POST" if _tool.method != "GET" else "GET"
        _tool.handler = _coerced(_tool)
    app.include_router(create_mcp_router(_tools, service_name="wardrobe"))
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=wardrobe reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_wardrobe"))
try:
    mount_missing_rest_routes(app, _tools, service_name="wardrobe")
except NameError:
    pass


# ── Hub registration ─────────────────────────────────────────────────────────
# LLM use cases: the chain (it must see images) is chosen in Oracle → Cervello → Modelli.
LLM_USECASES = [llm_usecase("wardrobe.foto", "Guardaroba · foto dei capi", chain="visione",
                            help="Descrive la foto di un nuovo capo (nome, categoria, colori, stile).")]


def _registration() -> dict:
    caps = {"mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp", "module_tool_domains": ["wardrobe"],
            "context_endpoint": "/api/module/context", **llm_capabilities(LLM_USECASES)}
    try:
        caps.update(ui.capabilities(SERVICE_BASE_URL))
        caps.update(transfer.capabilities())
    except Exception as exc:
        logger.warning("[🔄] event=wardrobe_ui_manifest_failed error=%s fallback=no_ui", exc)
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
    """Load the mirror and seed the vocabularies in the background (never block startup on Archive)."""
    import time
    for attempt in range(1, 1000):
        try:
            if store.refresh(force=True):
                wardrobe.ensure_vocabularies()
                signals.changed()
                return
        except Exception as exc:
            logger.warning("[🔄] event=wardrobe_warmup_failed attempt=%d error=%s", attempt, exc)
        time.sleep(min(60, 5 * attempt))


@app.on_event("startup")
def startup():
    try:
        _register()
    except Exception as exc:
        logger.warning("[🔄] event=hub_registration_failed_non_fatal error=%s", exc)
    from hestia_common.startup_utils import start_hub_keepalive
    start_hub_keepalive(_register, logger=logger, name="wardrobe-hub-keepalive")
    settings.start()
    agenda.register_async(_agenda_rules)
    threading.Thread(target=_warm_up, daemon=True, name="wardrobe-warmup").start()

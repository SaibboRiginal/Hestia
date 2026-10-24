import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4
import requests

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from tools.geocoding import GeocodingService
from tools.retrieval import ScoutRetrievalService
from tools.schemas import ModuleToolQueryRequest, RealEstateSearchRequest
from worker.runner import ScoutWorker
from core import scout_settings
from core.scout_settings import settings as scout_central_settings

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import (
        hub_health_url,
        wait_for_http_ready,
        wait_for_hub_services,
    )
    from hestia_common.agenda_client import AgendaClient
    from hestia_common.mail_client import MailClient, mail_rule
    from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase as llm_usecase
    from hestia_common import recap
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import (
        hub_health_url,
        wait_for_http_ready,
        wait_for_hub_services,
    )
    from hestia_common.agenda_client import AgendaClient
    from hestia_common.mail_client import MailClient, mail_rule
    from hestia_common.oracle_usecases import capabilities as llm_capabilities, usecase as llm_usecase
    from hestia_common import recap

logger, log_buffer = setup_service_logging("hestia_scout")

# What Scout asks Oracle for (the chain is chosen by Marko in Oracle → Cervello → Modelli).
LLM_USECASES = [llm_usecase("scout.annunci", "Scout · lettura annunci", chain="veloce",
                            help="Estrae i dati degli annunci dalle mail di Scout.")]

TARGET_DOMAIN = "real_estate"




class ModuleMaintenanceRequest(BaseModel):
    source: str = "oracle"
    task_id: str | None = None
    issue: str | None = None
    requested_action: str | None = "reconcile_entities"
    environment: str = "dev"
    dry_run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModuleMaintenanceResponse(BaseModel):
    status: str
    service: str
    dry_run: bool
    task_id: str
    executed_at: datetime
    retriable: bool
    summary: str
    mutation_count: int
    details: dict[str, Any]


api_app = FastAPI(title="Hestia Scout Tools", version="2.0.0")
api_app.add_middleware(CORSMiddleware, allow_origins=[
                       "*"], allow_methods=["*"], allow_headers=["*"])

# ── MCP endpoint ──────────────────────────────────────────────────────────
try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router
    _HAS_MCP = True
except ModuleNotFoundError:
    _HAS_MCP = False


def _build_retrieval_service() -> ScoutRetrievalService:
    archive_api_url = os.getenv(
        "ARCHIVE_API_URL", "http://hestia_archive:19002/api/archive")
    hub_api_url = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")
    geocoder = GeocodingService(user_agent="hestia-scout-tools/1.0")
    return ScoutRetrievalService(
        archive_api_url=archive_api_url,
        target_domain=TARGET_DOMAIN,
        geocoder=geocoder,
        hub_api_url=hub_api_url,
    )


retrieval_service = _build_retrieval_service()
worker = ScoutWorker(target_domain=TARGET_DOMAIN)


# ── Email by PUSH (SPEC docs/work/2026-10-19-email-push-spese) ─────────────
# Scout no longer polls: it subscribes to Iris with its mail rules (scout.mail.*). Iris stores each matching
# mail in Archive (domain real_estate) and calls POST /api/scout/mail; the cycle processes the pending records.
# The old agenda job "scout.email_cycle" is retired on existing installs.
MAIL_KEY = "listings"
RETIRED_AGENDA_JOBS = ["scout.email_cycle"]
mail = MailClient("scout")
agenda = AgendaClient("scout")

_cycle_lock = threading.Lock()
_cycle_state: dict[str, Any] = {"running": False, "last_started": None, "last_finished": None,
                                "last_trigger": None, "last_error": None, "last_ts": 0.0}


def _mail_rules() -> list[dict]:
    senders, queries = scout_settings.mail_rule_parts()
    return [mail_rule(MAIL_KEY, "Annunci immobiliari", path="/api/scout/mail", domain=TARGET_DOMAIN,
                      senders=senders, queries=queries,
                      description="Email dei portali immobiliari: Scout estrae e aggiorna gli immobili.")]


def _on_settings_change(changed: dict) -> None:
    """New senders / searches → the subscription in Iris follows at once."""
    if changed.keys() & {scout_settings.MAIL_SENDERS, scout_settings.MAIL_FILTER_QUERIES}:
        logger.info("event=scout_mail_rules_changed keys=%s", ",".join(sorted(changed)))
        mail.refresh()


scout_central_settings.on_change(_on_settings_change)


def run_cycle_guarded(trigger: str) -> dict:
    """One cycle at a time; concurrent triggers (agenda, fallback, user) are skipped."""
    if not _cycle_lock.acquire(blocking=False):
        return {"status": "busy", "started_at": _cycle_state["last_started"]}
    try:
        _cycle_state.update(running=True, last_trigger=trigger, last_error=None,
                            last_started=datetime.now(timezone.utc).isoformat(), last_ts=time.time())
        worker.run_cycle()
        return {"status": "ok", "trigger": trigger}
    except Exception as error:
        _cycle_state["last_error"] = str(error)[:300]
        logger.error("[🔄] event=scout_cycle_failed trigger=%s error=%s", trigger, error)
        return {"status": "error", "trigger": trigger, "error": str(error)[:300]}
    finally:
        _cycle_state.update(running=False, last_finished=datetime.now(timezone.utc).isoformat())
        _cycle_lock.release()


class CycleRequest(BaseModel):
    trigger: str = "api"
    wait: bool = False


@api_app.post("/api/scout/cycle")
def scout_cycle(req: CycleRequest | None = None):
    """Run the email→listing cycle. Default async (the agenda/Hub call returns at once)."""
    req = req or CycleRequest()
    if req.wait:
        return run_cycle_guarded(req.trigger)
    if _cycle_state["running"]:
        return {"status": "busy", "started_at": _cycle_state["last_started"]}
    threading.Thread(target=run_cycle_guarded, args=(req.trigger,), daemon=True,
                     name="scout-cycle").start()
    return {"status": "started", "trigger": req.trigger}


@api_app.get("/api/scout/cycle")
def scout_cycle_status():
    return {"status": "ok", "mail": "push", "subscription": f"scout:{MAIL_KEY}",
            **{k: v for k, v in _cycle_state.items() if k != "last_ts"}}


class MailDelivery(BaseModel):
    owner: str = "scout"
    key: str = MAIL_KEY
    domain: str = TARGET_DOMAIN
    count: int = 0
    reference_ids: list[str] = Field(default_factory=list)
    source: str = "watch"


@api_app.post("/api/scout/mail")
def scout_mail(req: MailDelivery | None = None):
    """Iris rang: new listing mails are waiting in Archive → run the cycle on them (async)."""
    req = req or MailDelivery()
    logger.info("event=scout_mail_delivered count=%d source=%s", req.count, req.source)
    return scout_cycle(CycleRequest(trigger=f"mail:{req.source}"))


def check_now(days: int = 1) -> dict:
    """«Controlla ora»: ask Iris to pass again the listing mails of the last days, then run the cycle."""
    def _run():
        mail.backfill(MAIL_KEY, days)       # delivered mails ring /api/scout/mail
        run_cycle_guarded("user")           # pending records even when nothing new arrived
    threading.Thread(target=_run, daemon=True, name="scout-check-now").start()
    return {"status": "started", "trigger": "user"}


@api_app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_scout_tools"}


@api_app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_scout",
        "count": len(rows),
        "logs": rows,
    }

api_app.include_router(create_log_control_router("hestia_scout"))
api_app.include_router(scout_central_settings.router())  # Themis: /api/settings/effective|reload

# ── WebUI plugin (client plugins SPEC §5): /api/ui/* data + manifest + bundle files ──
from core.archive_client import ArchiveClient
from ui_api import ListingStore, build_router as build_ui_router, plugin as ui_plugin, recap_facts

ui_store = ListingStore(ArchiveClient(api_url="", hub_api_url=os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")),
                        TARGET_DOMAIN)
api_app.include_router(ui_plugin.router())
api_app.include_router(build_ui_router(
    ui_store, run_cycle=check_now, cycle_status=scout_cycle_status))
api_app.include_router(recap.recap_router(
    "scout", lambda day, nxt: recap.piece("scout", "Case", icon="home", emoji="🏠", order=20,
                                         **recap_facts(ui_store.views(), day))))

# ── export / import (hestia_common.transfer): the listings with the user's own marks ─────────────────────
from hestia_common.transfer import Section, Transfer
from ui_api import to_view as _listing_view


class ListingsSection(Section):
    """Archive entities of Scout's domain. Import upserts (Archive merges the payload); Sostituisci never
    deletes: listings come back from the mail cycle anyway."""

    def __init__(self, store: ListingStore):
        super().__init__("annunci", "Annunci", icon="home", deletes=False)
        self.store = store

    def records(self, *, deleted: bool = False) -> list[dict]:
        return [{"key": str(r.get("entity_id")), "status": r.get("status") or "active",
                 "payload": r.get("payload") or {}, "updated_at": r.get("updated_at")}
                for r in self.store.records(fresh=True) if r.get("entity_id")]

    def title(self, rec: dict) -> str:
        return _listing_view({"entity_id": rec["key"], "payload": rec.get("payload") or {}})["title"]

    def subtitle(self, rec: dict) -> str:
        v = _listing_view({"entity_id": rec["key"], "payload": rec.get("payload") or {}})
        return " · ".join(str(x) for x in (v.get("city"), v.get("price") and f"{v['price']} €") if x)

    def same(self, a: dict, b: dict) -> bool:
        return a.get("payload") == b.get("payload") and a.get("status") == b.get("status")

    def write(self, records: list[dict], deletes: list[dict], *, mode: str) -> None:
        for r in records:
            if not self.store.archive.upsert_entity({"entity_id": r["key"], "domain": self.store.domain,
                                                     "status": r.get("status") or "active",
                                                     "payload": r.get("payload") or {}}):
                raise RuntimeError("archivio non raggiungibile")
        self.store.records(fresh=True)


transfer = Transfer("scout", sections=[ListingsSection(ui_store)])
api_app.include_router(transfer.router())


@api_app.post("/api/scout/check")
def scout_check():
    """«Controlla email»: Iris backfill (last day) + cycle."""
    return check_now()

@api_app.get("/api/module-tools/domains")
def list_module_domains():
    return {"domains": [TARGET_DOMAIN]}


@api_app.post("/api/module-tools/query")
def module_query(req: ModuleToolQueryRequest):
    if req.domain != TARGET_DOMAIN:
        return {"items": []}

    specialized_request = retrieval_service.from_module_query(req)
    items = retrieval_service.search(specialized_request)
    return {"domain": req.domain, "items": items}


@api_app.get("/api/tools")
def list_tools():
    return {
        "tools": [
            {
                "name": "real_estate.search",
                "path": "/api/tools/real_estate/search",
                "description": "Domain retrieval using stored entity geo coordinates and preference constraints",
            }
        ]
    }


@api_app.post("/api/tools/real_estate/search")
def search_real_estate(req: RealEstateSearchRequest):
    items = retrieval_service.search(req)
    text = retrieval_service.search_formatted(req, items)
    return {"text": text, "domain": TARGET_DOMAIN, "count": len(items), "display": retrieval_service.display_of(items)}


@api_app.post("/api/module/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def module_maintenance_reconcile(req: ModuleMaintenanceRequest):
    task_id = str(req.task_id or uuid4())
    if req.dry_run:
        return ModuleMaintenanceResponse(
            status="ok",
            service="scout",
            dry_run=True,
            task_id=task_id,
            executed_at=datetime.now(timezone.utc),
            retriable=True,
            summary="Scout maintenance dry-run accepted: no mutations executed.",
            mutation_count=0,
            details={
                "requested_action": req.requested_action,
                "note": "Set dry_run=false to execute reconciliation.",
            },
        )

    worker.reconcile_entities()
    return ModuleMaintenanceResponse(
        status="ok",
        service="scout",
        dry_run=False,
        task_id=task_id,
        executed_at=datetime.now(timezone.utc),
        retriable=True,
        summary="Scout maintenance reconcile completed.",
        mutation_count=0,
        details={
            "requested_action": req.requested_action,
            "note": "Reconciliation executed; check Scout logs for detailed mutation counts.",
        },
    )


@api_app.post("/api/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def maintenance_reconcile_alias(req: ModuleMaintenanceRequest):
    return module_maintenance_reconcile(req)


def _start_tools_api():
    # SCOUT_TOOLS_PORT: HTTP port for the tools API
    port = int(os.getenv("SCOUT_TOOLS_PORT", "19006"))

    def run_server():
        uvicorn.run(
            api_app,
            host="0.0.0.0",
            port=port,
            log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
        )

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    logger.info(
        "event=scout_tools_api_online Scout tools API online at 0.0.0.0:%d", port)


# ── MCP Tools ──────────────────────────────────────────────────────────────
if _HAS_MCP:
    from tools.schemas import RealEstateSearchRequest

    def _mcp_scout_search(query: str = "", filters: dict | None = None,
                          filters_gt: dict | None = None, filters_lt: dict | None = None,
                          sort_by: str | None = None, sort_order: str = "desc",
                          limit: int = 30) -> dict:
        req = RealEstateSearchRequest(
            domain=TARGET_DOMAIN, query=query,
            filters=filters or {}, filters_gt=filters_gt or {},
            filters_lt=filters_lt or {}, sort_by=sort_by,
            sort_order=sort_order, limit=limit,
        )
        return {"domain": TARGET_DOMAIN, "items": retrieval_service.search(req)}

    def _mcp_scout_listings(query: str = "", limit: int = 50) -> dict:
        req = RealEstateSearchRequest(domain=TARGET_DOMAIN, query=query, limit=limit)
        return {"text": retrieval_service.search_formatted(req)}

    def _mcp_scout_reconcile(dry_run: bool = False) -> dict:
        if dry_run:
            return {"status": "dry_run", "message": "Dry run requested — no changes made."}
        worker.reconcile_entities()
        return {"status": "ok", "message": "Reconcile completed. Check logs for details."}

    def _mcp_scout_fetch() -> dict:
        """Trigger a full email fetch + parse + extract cycle on demand."""
        check_now()
        return {"status": "ok", "message": "Controllo avviato: le email annunci dell'ultimo giorno vengono "
                                           "ripassate e lette."}

    def _mcp_scout_stats() -> dict:
        """Return real_estate domain summary: counts, statuses, date ranges."""
        entities = retrieval_service._fetch_archive_entities(
            RealEstateSearchRequest(domain=TARGET_DOMAIN, limit=100))
        total = len(entities)
        status_counts: dict[str, int] = {}
        newest = None
        oldest = None
        for e in entities:
            st = str((e.get("listing_status") or e.get("payload", {}).get("listing_status") or "unknown")).strip().lower()
            status_counts[st] = status_counts.get(st, 0) + 1
            ct = e.get("created_at")
            if ct:
                if newest is None or ct > newest:
                    newest = ct
                if oldest is None or ct < oldest:
                    oldest = ct
        return {
            "domain": TARGET_DOMAIN,
            "total_entities": total,
            "by_status": status_counts,
            "oldest_created": str(oldest) if oldest else None,
            "newest_created": str(newest) if newest else None,
            "display": stats_display(total, status_counts, newest),
        }

    def stats_display(total: int, by_status: dict, newest) -> dict:
        from hestia_common.display import action, display, item
        names = {"available": "disponibili", "sold": "vendute", "rented": "affittate", "removed": "tolte",
                 "unknown": "senza stato"}
        when = str(newest or "")[:10]
        return display("Case", subtitle=f"{total} annunci", footer=f"Ultimo arrivato il {when[8:10]}/{when[5:7]}" if when else "",
                       items=[item(names.get(k, k.replace("_", " ")), [str(v)]) for k, v in sorted(by_status.items(),
                                                                                         key=lambda kv: -kv[1])],
                       actions=[action("Case disponibili", "scout_listings", style="primary"), action("Cerca", "scout.search")])

    mcp_tools = [
        MCPTool(name="scout.search",
                description="Search real estate listings by query, city, price range, surface, rooms.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Free-text search query"},
                        "filters": {"type": "object", "description": "Exact-match filters (city, type)"},
                        "filters_gt": {"type": "object", "description": "Numeric > filters (price_min)"},
                        "filters_lt": {"type": "object", "description": "Numeric < filters (price_max)"},
                        "sort_by": {"type": "string"},
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                        "limit": {"type": "integer", "description": "Max results (default 30)"},
                    },
                }, handler=_mcp_scout_search,
                title="Cerca case", method="POST", path="/api/tools/real_estate/search",
                clients=["*"], response_mode="oracle_natural", response_prompt="",
                telegram_visible=True, telegram_group="case",
                telegram={"section": "Case", "primary": 2}),
        MCPTool(name="scout_listings",
                description="Show available real estate listings. Use when user wants to browse listings.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (city, neighborhood)"},
                        "limit": {"type": "integer", "description": "Max results (default 50)"},
                    },
                }, handler=_mcp_scout_listings,
                title="Case disponibili", method="POST", path="/api/tools/real_estate/search",
                clients=["telegram", "ui"], response_mode="oracle_natural",
                response_prompt="Mostra una lista breve e leggibile delle case trovate con punti chiave e link.",
                telegram_visible=True, telegram_group="case",
                telegram={"section": "Case", "primary": 1}),
        MCPTool(name="scout_reconcile",
                description="Run Scout data reconciliation maintenance.",
                parameters={
                    "type": "object",
                    "properties": {
                        "dry_run": {"type": "boolean", "description": "Simulate without changes"},
                    },
                }, handler=_mcp_scout_reconcile,
                title="Riconcilia case", method="POST", path="/api/module/maintenance/reconcile",
                clients=["telegram", "ui"], response_mode="oracle_natural",
                response_prompt="Riassumi esito della riconciliazione Scout, indicando se era dry-run e cosa e stato verificato.",
                telegram_visible=True, telegram_group="case",
                telegram={"section": "Avanzate"}),
        MCPTool(name="scout_fetch",
                description="Check listing emails NOW: Iris passes the last day's listing mails again and Scout "
                            "parses and extracts them (new mails normally arrive by themselves). "
                            "Use when the user wants to check for new house listings NOW.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=_mcp_scout_fetch,
                title="Controlla email delle case", method="POST", path="/api/scout/check",
                clients=["telegram", "ui"], response_mode="oracle_natural",
                response_prompt="Conferma che il ciclo fetch è stato avviato e di controllare i log.",
                telegram_visible=True, telegram_group="case",
                telegram={"section": "Case", "primary": 3, "label": "Controlla email"}),
        MCPTool(name="scout_stats",
                description="Return real_estate domain statistics: total entities, "
                            "breakdown by listing status (available/sold/etc), "
                            "and date range of when listings were added.",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=_mcp_scout_stats,
                title="Statistiche case", method="GET", path="/api/scout/stats",
                clients=["telegram", "ui"], response_mode="oracle_natural",
                response_prompt="Mostra le statistiche del dominio immobiliare in formato leggibile.",
                telegram_visible=True, telegram_group="case",
                telegram={"section": "Case", "summary": True}),
    ]
    api_app.include_router(create_mcp_router(mcp_tools, service_name="scout"))
    # REST paths of MCP-only tools (scout_stats → GET /api/scout/stats); Hub/Telegram call by path.
    from hestia_common.mcp_helpers import mount_missing_rest_routes
    mount_missing_rest_routes(api_app, mcp_tools, service_name="scout")
    logger.info("event=mcp_router_mounted service=scout tools=%d", len(mcp_tools))


def _register_with_hub(port: int):
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "SCOUT_SERVICE_BASE_URL", f"http://hestia_scout:{port}")
    payload = {
        "name": "scout",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "module",
        "service_version": os.getenv("SCOUT_SERVICE_VERSION", "1.0.0"),
        "tags": ["module", "real_estate"],
        "topology_tags": ["layer:domain", "domain:real_estate", "status:stable"],
        "capabilities": {
            "when_to_use": 'ricerca casa: annunci immobiliari, filtri, preferiti', "manual": "Cerca annunci immobiliari con i filtri dell'utente, preferiti, avvisi sui nuovi annunci.",
            "module_tool_domains": [TARGET_DOMAIN],
            "module_tool_endpoint": f"{service_base_url.rstrip('/')}/api/module-tools",
            "mcp_endpoint": f"{service_base_url.rstrip('/')}/mcp",
            **ui_plugin.capabilities(service_base_url),
            **llm_capabilities(LLM_USECASES),
            **recap.capabilities(),
            **transfer.capabilities(),
        },
    }
    try:
        requests.post(f"{hub_api_url}/registry/register",
                      json=payload, timeout=4)
        logger.debug("event=registered_hub_hub_base_url Registered on Hub | hub=%s base_url=%s",
                     hub_api_url, service_base_url)
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", error)


if __name__ == "__main__":
    load_dotenv()
    tools_port = int(os.getenv("SCOUT_TOOLS_PORT", "19006"))
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    startup_wait_timeout = float(
        os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))

    wait_for_http_ready(
        hub_health_url(hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )
    wait_for_hub_services(
        hub_api_url,
        ["archive", "hecate"],
        timeout_seconds=startup_wait_timeout,
        logger=logger,
    )

    _start_tools_api()
    scout_central_settings.start()
    _register_with_hub(tools_port)
    # Periodically re-register with Hub so a Hub restart doesn't lose this service.

    def _hub_keepalive():
        while True:
            time.sleep(60)
            try:
                _register_with_hub(tools_port)
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s", error)
    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()

    mail.subscribe_async(_mail_rules)
    threading.Thread(target=lambda: agenda.retire(RETIRED_AGENDA_JOBS), daemon=True,
                     name="scout-agenda-retire").start()

    # Mails that arrived while Scout was down wait in Archive: process them once at boot, then Iris rings.
    run_cycle_guarded("startup")
    while True:
        time.sleep(3600)

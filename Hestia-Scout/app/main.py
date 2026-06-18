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

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import (
        hub_health_url,
        wait_for_http_ready,
        wait_for_hub_services,
    )
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

logger, log_buffer = setup_service_logging("hestia_scout")

TARGET_DOMAIN = "real_estate"
TARGET_SOURCE = "iris_email"


def _build_target_filters():
    explicit_filters = [
        item.strip()
        for item in os.getenv("SCOUT_FILTER_QUERIES", "").split("||")
        if item.strip()
    ]
    if explicit_filters:
        return explicit_filters

    sender_list_raw = os.getenv(
        "SCOUT_EMAIL_SENDERS",
        "nonrispondere@idealista.it,noreply@notifiche.immobiliare.it",
    )
    senders = [
        sender.strip()
        for sender in sender_list_raw.split(",")
        if sender.strip()
    ]
    return [f'FROM "{sender}"' for sender in senders]


TARGET_FILTERS = _build_target_filters()


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
worker = ScoutWorker(
    target_domain=TARGET_DOMAIN,
    target_source=TARGET_SOURCE,
    target_filters=TARGET_FILTERS,
)


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
    return retrieval_service.search(req)


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
        return {"domain": TARGET_DOMAIN, "items": retrieval_service.search_and_format(req)}

    def _mcp_scout_listings(query: str = "", limit: int = 50) -> dict:
        req = RealEstateSearchRequest(domain=TARGET_DOMAIN, query=query, limit=limit)
        return {"domain": TARGET_DOMAIN, "items": retrieval_service.search_and_format(req)}

    def _mcp_scout_reconcile(dry_run: bool = True) -> dict:
        return retrieval_service.reconcile_entities(dry_run=dry_run)

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
                title="\U0001f50d Cerca immobili", method="POST", path="/api/tools/real_estate/search",
                clients=["*"], response_mode="oracle_natural", response_prompt="",
                telegram_visible=True, telegram_group="immobiliare"),
        MCPTool(name="scout_listings",
                description="Show available real estate listings. Use when user wants to browse listings.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query (city, neighborhood)"},
                        "limit": {"type": "integer", "description": "Max results (default 50)"},
                    },
                }, handler=_mcp_scout_listings,
                title="\U0001f3e0 Case disponibili", method="POST", path="/api/tools/real_estate/search",
                clients=["telegram", "ui"], response_mode="oracle_natural",
                response_prompt="Mostra una lista breve e leggibile delle case trovate con punti chiave e link.",
                telegram_visible=True, telegram_group="immobiliare"),
        MCPTool(name="scout_reconcile",
                description="Run Scout data reconciliation maintenance.",
                parameters={
                    "type": "object",
                    "properties": {
                        "dry_run": {"type": "boolean", "description": "Simulate without changes"},
                    },
                }, handler=_mcp_scout_reconcile,
                title="\U0001f6e0️ Riconcilia Scout", method="POST", path="/api/module/maintenance/reconcile",
                clients=["telegram", "ui"], response_mode="oracle_natural",
                response_prompt="Riassumi esito della riconciliazione Scout, indicando se era dry-run e cosa e stato verificato.",
                telegram_visible=True, telegram_group="immobiliare"),
    ]
    api_app.include_router(create_mcp_router(mcp_tools, service_name="scout"))
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
            "module_tool_domains": [TARGET_DOMAIN],
            "module_tool_endpoint": f"{service_base_url.rstrip('/')}/api/module-tools",
            "mcp_endpoint": f"{service_base_url.rstrip('/')}/mcp",
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

    # SCOUT_POLL_INTERVAL_SECONDS: seconds between email polling cycles (default 1800 = 30 min)
    poll_interval = int(os.getenv("SCOUT_POLL_INTERVAL_SECONDS", "1800"))
    while True:
        try:
            worker.run_cycle()
        except Exception as error:
            logger.error(
                "event=critical_error_scout_polling_loop Critical error in Scout polling loop: %s", error)

        logger.info(
            "event=scout_resting_seconds_before_next Scout resting for %d seconds before next cycle", poll_interval)
        time.sleep(poll_interval)

"""Hestia-Argus — FastAPI application entry point."""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core import context_loader, hub_client
from core.argus_settings import settings as argus_settings
from core.health_poller import poll_all
from core.hub_client import discover_services
from schemas.reports import SystemReport
from core.ui_plugin import ui
from services import analysis_service, health_history, monitor_service, performance

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready

logger, log_buffer = setup_service_logging("hestia_argus")


class RemediationRequest(BaseModel):
    service: str
    issue: str
    severity: str = "warning"
    requested_action: str = "runbook_autoselect"
    environment: str = "dev"
    dry_run: bool = True
    auto_approve: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)


# Loaded once at startup; injected into Oracle calls.
_project_context: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _project_context
    # Load Hestia project docs for Oracle context.
    _project_context = context_loader.get_context()
    logger.info(
        "event=project_context_loaded_chars Project context loaded (%d chars)", len(
            _project_context)
    )
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
    # Register with Hub (non-fatal).
    hub_client.register()
    # Periodically re-register with Hub so a Hub restart doesn't lose this service.

    def _hub_keepalive():
        while True:
            time.sleep(60)
            try:
                hub_client.register(quiet_success=True)
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s", error)
    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()
    # Central settings (Themis): background load + hourly re-assert; defaults until it answers.
    argus_settings.start()
    # Start background monitoring loop.
    monitor_service.start()
    yield


app = FastAPI(
    title="Hestia-Argus",
    description="All-seeing system monitor for the Hestia ecosystem",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────────────
#  MCP tools
# ─────────────────────────────────────────────────────────────────────

try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    _argus_mcp_tools = [
        MCPTool(
            name="system_status",
            description="Show the health of all the assistant's services",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "system_status", "params": kw},
            title="alt::System status", method="GET", path="/api/argus/status",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            response_prompt=(
                ("Be VERY brief. One opening line with the count (e.g. '9/9 servizi online'). Then a bullet list "
                 "• per service: name if up, name — reason if down/degraded. If everything works write only the "
                 "opening line, no list. No extra paragraph, no conclusion.")
            ),
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Salute e log", "summary": True}),
        MCPTool(
            name="system_log",
            description="Show the recent errors and warnings of the services",
            parameters={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Optional service name filter"},
                    "level": {"type": "string", "description": "Minimum log level (WARNING/ERROR/CRITICAL)"},
                    "since": {"type": "string", "description": "Time window e.g. 30m, 1h"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "system_log", "params": kw},
            title="System logs", method="GET", path="/api/argus/logs",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            response_prompt=(
                ("Be VERY brief. No events: one sentence 'Nessun warning recente.' Otherwise: one line with the "
                 "total, then a bullet • per problem as '• [LEVEL] service — short message'. Group by service "
                 "when several come from the same one. No intro, no conclusion.")
            ),
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Salute e log", "label": "Logs"}),
        MCPTool(
            name="system_analysis",
            description="Run a full AI analysis of the services",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "system_analysis", "params": kw},
            title="System analysis", method="POST", path="/api/argus/analyze",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                ("Be brief and direct. ALWAYS this structure: 1) One line of overall state (e.g. 'Sistema sano' "
                 "or 'X problemi rilevati'). 2) If there are problems: a bullet list • per issue — service, "
                 "symptom, likely cause. 3) If needed: a bullet list • of suggested actions, max 3. Prefer "
                 "bullets to paragraphs. No opening or closing text. Use the 'summary' field as the base (the AI "
                 "analysis already done).")
            ),
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Salute e log", "label": "Analisi"}),
        MCPTool(
            name="system_performance",
            description="Module performance: memory, CPU, response times, data size",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "system_performance", "params": kw},
            title="Performance", method="GET", path="/api/argus/performance",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            response_prompt=(
                ("Be brief. One summary line (e.g. 'Tutto nella norma'). Then only the modules above or near the "
                 "limits in 'thresholds': '• name — memory MB · CPU % · response ms'. Then one line on stored "
                 "data (GB and growth of the day) if 'storage' is there. No conclusion.")
            ),
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Salute e log", "label": "Performance"}),
        MCPTool(
            name="system_incidents",
            description="History of the problems and of what was done to fix them (alerts, restarts, re-checks)",
            parameters={"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Closed problems to show (default 10)"}}},
            handler=lambda **kw: {"status": "ok", "tool": "system_incidents", "params": kw},
            title="Repair history", method="GET", path="/api/argus/incidents",
            clients=["telegram", "ui", "external"], response_mode="oracle_natural",
            response_prompt=(
                ("Be brief. First the open problems, then the most recent closed ones: '• service — when — what "
                 "was done — how it ended'. If none: one sentence.")
            ),
            telegram_visible=True, telegram_group="sistema",
                telegram={"section": "Repairs", "label": "History"}),
    ]
    app.include_router(create_mcp_router(_argus_mcp_tools, service_name="argus"))
    logger.info("event=mcp_router_mounted service=argus")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=argus reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_argus"))
app.include_router(argus_settings.router())
app.include_router(ui.router())   # GET /api/ui/manifest · GET /ui/webui/<file> (WebUI plugin)

# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "argus"}


@app.get("/api/logs", tags=["meta"])
def service_logs(limit: int = 200, level: str | None = None, contains: str | None = None) -> dict:
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_argus",
        "count": len(rows),
        "logs": rows,
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/argus/status", tags=["argus"])
def get_status() -> dict:
    """Return a live health snapshot for every registered service."""
    services = discover_services()
    health = poll_all(services)
    healthy = sum(1 for r in health.values() if r.status == "up")
    unhealthy = sum(1 for r in health.values() if r.status != "up")
    return {
        "healthy_count": healthy,
        "unhealthy_count": unhealthy,
        "services": {name: r.model_dump() for name, r in health.items()},
    }


@app.get("/api/argus/logs", tags=["argus"])
def get_logs(
    service: str | None = Query(
        default=None, description="Filter by service name"),
    level: str = Query(default="WARNING", description="Minimum log level"),
    since: str = Query(default="30m", description="Time window, e.g. 30m, 2h"),
) -> dict:
    """Return recent log events filtered by service, level and time window."""
    events = analysis_service.get_filtered_logs(
        service_name=service, since=since, level=level
    )
    return {
        "count": len(events),
        "filters": {"service": service, "level": level, "since": since},
        "events": [e.model_dump() for e in events],
    }


@app.get("/api/argus/overview", tags=["argus"])
def get_overview() -> dict:
    """Last monitor cycle in one look (no network): healthy/total, services not up, open incidents."""
    return health_history.overview()


@app.get("/api/argus/history", tags=["argus"])
def get_history(
    minutes: int = Query(default=360, ge=5, le=1440, description="Window in minutes (max 24 h)"),
    buckets: int = Query(default=60, ge=1, le=240, description="Strip length (worst status per bucket)"),
) -> dict:
    """Health per service over time (in memory, since Argus started): strip u/w/d/- per bucket + uptime %."""
    return health_history.history(minutes=minutes, buckets=buckets)


@app.get("/api/argus/incidents", tags=["argus"])
def get_incidents(limit: int = Query(default=20, ge=0, le=200, description="Closed incidents to return")) -> dict:
    """Open incidents and the journal of closed ones (kept in Archive), each with what Argus did (alert, automatic
    restart, repair, recheck, giving up, recovery)."""
    return health_history.incidents(limit=limit)


@app.get("/api/argus/performance", tags=["argus"])
def get_performance() -> dict:
    """Last performance sample (no network): per module CPU %, memory, response time, uptime, restarts; Hub
    round trip; storage size and growth; the Themis thresholds (Cindy D16 + 25)."""
    return performance.snapshot()


@app.get("/api/argus/performance/history", tags=["argus"])
def get_performance_history(
    service: str | None = Query(default=None, description="Only this module"),
    hours: int = Query(default=24, ge=1, le=24, description="Window in hours (max 24, in memory)"),
) -> dict:
    """Performance samples over time per module, plus storage size samples (last 7 days)."""
    return performance.history(service=service, hours=hours)


@app.get("/api/argus/recheck-targets", tags=["argus"])
def get_recheck_targets() -> dict:
    """Quick-action chips «Ricontrolla <servizio>»: one per service that is not up."""
    return {"items": health_history.recheck_targets()}


@app.post("/api/argus/analyze", tags=["argus"])
def analyze() -> dict:
    """Full system analysis — health snapshot + Oracle LLM summary."""
    report: SystemReport = analysis_service.build_system_report(
        project_context=_project_context
    )
    return report.model_dump(mode="json")


@app.post("/api/argus/recheck/{service}", tags=["argus"])
def recheck_service(service: str) -> dict:
    """Repair follow-up fired by the assistant agenda (argus.repair.<service>)."""
    return monitor_service.recheck(service)


@app.post("/api/argus/remediate", tags=["argus"])
def request_remediation(req: RemediationRequest) -> dict:
    ok, result = hub_client.request_hephaestus_remediation(
        source="argus",
        service=req.service,
        issue=req.issue,
        severity=req.severity,
        requested_action=req.requested_action,
        environment=req.environment,
        dry_run=req.dry_run,
        auto_approve=req.auto_approve,
        metadata=req.metadata,
    )
    return {
        "status": "ok" if ok else "error",
        "forwarded_to": "hephaestus",
        "result": result,
    }

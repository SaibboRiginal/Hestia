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
from core.health_poller import poll_all
from core.hub_client import discover_services
from schemas.reports import SystemReport
from services import analysis_service, monitor_service

try:
    from hestia_common.logging_utils import setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging
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
            description="Mostra lo stato di salute di tutti i servizi Hestia",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "system_status", "params": kw},
            title="\U0001f5a5️ Stato sistema", method="GET", path="/api/argus/status",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Sii ESTREMAMENTE conciso. "
                "Una riga introduttiva con il conteggio (es. '9/9 servizi online'). "
                "Poi una lista puntata • con ogni servizio: ✅ nome se up, ❌ nome — motivo se down/degraded. "
                "Se tutto funziona scrivi solo la riga introduttiva senza lista. "
                "Nessun paragrafo aggiuntivo, nessuna conclusione."
            ),
            telegram_visible=True, telegram_group="sistema",
        ),
        MCPTool(
            name="system_log",
            description="Mostra gli errori e warning recenti dei servizi",
            parameters={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Optional service name filter"},
                    "level": {"type": "string", "description": "Minimum log level (WARNING/ERROR/CRITICAL)"},
                    "since": {"type": "string", "description": "Time window e.g. 30m, 1h"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "system_log", "params": kw},
            title="\U0001f4cb Log di sistema", method="GET", path="/api/argus/logs",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Sii ESTREMAMENTE conciso. "
                "Se non ci sono eventi: una sola frase '✅ Nessun warning recente.' "
                "Altrimenti: una riga con il totale, poi lista puntata • per ogni problema "
                "nel formato '• [LIVELLO] servizio — messaggio breve'. "
                "Raggruppa per servizio se ci sono più eventi dallo stesso. "
                "Nessun paragrafo introduttivo, nessuna conclusione."
            ),
            telegram_visible=True, telegram_group="sistema",
        ),
        MCPTool(
            name="system_analysis",
            description="Esegui un'analisi completa dei servizi con AI",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "system_analysis", "params": kw},
            title="\U0001f50d Analisi sistema", method="POST", path="/api/argus/analyze",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Sii conciso e diretto. Struttura SEMPRE così: "
                "1) Una riga di stato globale (es. '✅ Sistema sano' o '⚠️ X problemi rilevati'). "
                "2) Se ci sono problemi: lista puntata • con ogni issue — servizio, sintomo, causa probabile. "
                "3) Se necessario: lista puntata • con azioni suggerite, massimo 3. "
                "Preferisci liste puntate a paragrafi. Nessun testo introduttivo o di chiusura. "
                "Usa il campo 'summary' come base per l'analisi AI già elaborata."
            ),
            telegram_visible=True, telegram_group="sistema",
        ),
        MCPTool(
            name="system_remediate",
            description="Invia un remediation intent ad Hephaestus",
            parameters={
                "type": "object",
                "properties": {
                    "service": {"type": "string", "description": "Service target remediation"},
                    "issue": {"type": "string", "description": "Issue summary"},
                    "severity": {"type": "string", "description": "warning|error|critical"},
                    "requested_action": {"type": "string", "description": "Requested remediation action"},
                    "environment": {"type": "string", "description": "dev|staging|prod"},
                    "dry_run": {"type": "boolean", "description": "Remediation in dry-run mode"},
                    "auto_approve": {"type": "boolean", "description": "Allow policy auto-approval"},
                },
                "required": ["service", "issue"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "system_remediate", "params": kw},
            title="Avvia remediation sistema", method="POST", path="/api/argus/remediate",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="sistema",
        ),
    ]
    app.include_router(create_mcp_router(_argus_mcp_tools, service_name="argus"))
    logger.info("event=mcp_router_mounted service=argus")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=argus reason=hestia_common_not_available")


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


@app.post("/api/argus/analyze", tags=["argus"])
def analyze() -> dict:
    """Full system analysis — health snapshot + Oracle LLM summary."""
    report: SystemReport = analysis_service.build_system_report(
        project_context=_project_context
    )
    return report.model_dump(mode="json")


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

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

# Loaded once at startup; injected into Oracle calls.
_project_context: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _project_context
    # Load Hestia project docs for Oracle context.
    _project_context = context_loader.get_context()
    logger.info(
        "Project context loaded (%d chars)", len(_project_context)
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
                logger.warning("Hub keepalive registration failed: %s", error)
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

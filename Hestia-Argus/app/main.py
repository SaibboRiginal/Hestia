"""Hestia-Argus — FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Query

from core import context_loader, hub_client
from core.health_poller import poll_all
from core.hub_client import discover_services
from schemas.reports import SystemReport
from services import analysis_service, monitor_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("argus")

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
    # Register with Hub (non-fatal).
    hub_client.register()
    # Start background monitoring loop.
    monitor_service.start()
    yield


app = FastAPI(
    title="Hestia-Argus",
    description="All-seeing system monitor for the Hestia ecosystem",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "argus"}


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

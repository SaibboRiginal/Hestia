"""Hestia-Chronos — FastAPI entry point.

Provides a provider-agnostic HTTP API for calendar CRUD.
All endpoints are intended to be called through Hub routing; they are not
exposed to the outside world directly.
"""
from __future__ import annotations

import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from core.hub_client import register_on_hub
from providers.registry import CalendarProviderRegistry
from schemas.events import (
    CreateEventRequest,
    CreateEventResponse,
    DeleteEventRequest,
    ListEventsRequest,
    ListEventsResponse,
    UpdateEventRequest,
)
from services.calendar_service import CalendarService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("hestia_chronos")

# ─────────────────────────────────────────────────────────────────────
#  App bootstrap
# ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia Chronos", version="1.0.0")

_registry = CalendarProviderRegistry()
_service = CalendarService(_registry)

# ─────────────────────────────────────────────────────────────────────
#  Lifecycle
# ─────────────────────────────────────────────────────────────────────


@app.on_event("startup")
def on_startup() -> None:
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api"
    ).rstrip("/")
    service_base_url = os.getenv(
        "CALENDAR_SERVICE_BASE_URL", "http://hestia_chronos:19007"
    )

    status = _registry.status_report()
    logger.info(
        "[STARTUP] Active providers: %s | Unavailable: %s",
        status["active"],
        list(status["unavailable"].keys()),
    )

    register_on_hub(hub_api_url, service_base_url)


# ─────────────────────────────────────────────────────────────────────
#  Health
# ─────────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    status = _registry.status_report()
    return {
        "status": "ok",
        "service": "hestia_chronos",
        "providers": status,
    }


# ─────────────────────────────────────────────────────────────────────
#  Calendar endpoints
# ─────────────────────────────────────────────────────────────────────


@app.post("/api/calendar/events", response_model=CreateEventResponse)
def create_event(req: CreateEventRequest) -> CreateEventResponse:
    """Create a calendar event across one or more providers."""
    if not _registry.active_providers:
        raise HTTPException(
            status_code=503,
            detail="No calendar providers are configured and available.",
        )
    return _service.create_event(
        event=req.event,
        target_providers=req.target_providers,
        calendar_id=req.calendar_id,
    )


@app.post("/api/calendar/events/list", response_model=ListEventsResponse)
def list_events(req: ListEventsRequest) -> ListEventsResponse:
    """List events within a time window across one or more providers."""
    return _service.list_events(
        start=req.start_datetime,
        end=req.end_datetime,
        target_providers=req.target_providers,
        calendar_id=req.calendar_id,
        max_results=req.max_results,
    )


@app.delete("/api/calendar/events/{event_id}")
def delete_event(event_id: str, req: DeleteEventRequest) -> JSONResponse:
    """Delete a calendar event by its provider-issued ID."""
    result = _service.delete_event(
        event_id=event_id,
        provider_name=req.provider,
        calendar_id=req.calendar_id,
    )
    if not result["success"]:
        status_code = 404 if "not found" in (
            result.get("error") or "").lower() else 502
        raise HTTPException(status_code=status_code,
                            detail=result.get("error"))
    return JSONResponse({"success": True})


@app.patch("/api/calendar/events/{event_id}")
def update_event(event_id: str, req: UpdateEventRequest) -> JSONResponse:
    """Partially update an existing event."""
    result = _service.update_event(
        event_id=event_id,
        provider_name=req.provider,
        updates=req.updates,
        calendar_id=req.calendar_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result.get("error"))
    return JSONResponse({"success": True})


@app.get("/api/calendar/providers")
def list_providers() -> dict:
    """Return active and unavailable provider information."""
    return _registry.status_report()


# ─────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("CALENDAR_PORT", "8008"))
    uvicorn.run("main:app", host="0.0.0.0", port=port,
                reload=False)  # WORKDIR=/code, flat imports

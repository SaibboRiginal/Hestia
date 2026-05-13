"""Hestia-Chronos — FastAPI entry point.

Provides a provider-agnostic HTTP API for calendar CRUD.
All endpoints are intended to be called through Hub routing; they are not
exposed to the outside world directly.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core import archive_client
from core.hub_client import register_on_hub
from schemas.events import (
    CreateEventRequest,
    CreateEventResponse,
    DeleteEventRequest,
    ListEventsRequest,
    ListEventsResponse,
    UpdateEventRequest,
)
from services import notification_worker, sync_worker

try:
    from hestia_common.logging_utils import setup_service_logging
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
    from hestia_common.logging_utils import setup_service_logging
    from hestia_common.startup_utils import (
        hub_health_url,
        wait_for_http_ready,
        wait_for_hub_services,
    )

logger, log_buffer = setup_service_logging("hestia_chronos")

# ─────────────────────────────────────────────────────────────────────
#  App bootstrap
# ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia Chronos", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])


def _route_hecate(
    *,
    method: str,
    path: str,
    query: dict | None = None,
    body: dict | None = None,
    timeout_seconds: float = 20.0,
) -> tuple[int, dict]:
    import requests

    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    response = requests.post(
        f"{hub_api_url}/route/hecate/{path.lstrip('/')}",
        json={
            "method": method,
            "headers": {},
            "query": query or {},
            "body": body,
            "timeout_seconds": timeout_seconds,
        },
        timeout=max(5.0, timeout_seconds + 2.0),
    )
    response.raise_for_status()
    routed = response.json() if response.content else {}
    return int((routed or {}).get("status_code", 500)), (routed or {}).get("payload") or {}

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
        ["archive"],
        timeout_seconds=startup_wait_timeout,
        logger=logger,
    )

    register_on_hub(hub_api_url, service_base_url)
    # Periodically re-register with Hub so a Hub restart doesn't lose this service.

    def _hub_keepalive():
        while True:
            time.sleep(60)
            try:
                register_on_hub(
                    hub_api_url,
                    service_base_url,
                    max_attempts=1,
                    quiet_success=True,
                )
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed [HUB] Keepalive registration failed: %s", error)
    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()

    # Start the proactive notification worker (background daemon thread).
    notification_worker.start()
    # Start the calendar sync worker (pulls events from Hecate into Archive).
    sync_worker.start()


# ─────────────────────────────────────────────────────────────────────
#  Health
# ─────────────────────────────────────────────────────────────────────


@app.get("/health")
def health() -> dict:
    status_code, status_payload = _route_hecate(
        method="GET",
        path="/api/gateway/providers",
        timeout_seconds=10,
    )
    return {
        "status": "ok",
        "service": "hestia_chronos",
        "providers": status_payload if status_code < 400 else {},
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_chronos",
        "count": len(rows),
        "logs": rows,
    }


# ─────────────────────────────────────────────────────────────────────
#  Calendar endpoints
# ─────────────────────────────────────────────────────────────────────


@app.post("/api/calendar/events", response_model=CreateEventResponse)
def create_event(req: CreateEventRequest) -> CreateEventResponse:
    body = req.model_dump(mode="json")
    status_code, payload = _route_hecate(
        method="POST",
        path="/api/gateway/calendar/events",
        body=body,
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return CreateEventResponse.model_validate(payload)


@app.post("/api/calendar/events/list", response_model=ListEventsResponse)
def list_events(req: ListEventsRequest) -> ListEventsResponse:
    provider = req.target_providers[0] if req.target_providers else None
    query = {
        "start_datetime": req.start_datetime.isoformat(),
        "end_datetime": req.end_datetime.isoformat(),
        "provider": provider,
        "calendar_id": req.calendar_id,
        "max_results": req.max_results,
    }
    status_code, payload = _route_hecate(
        method="GET",
        path="/api/gateway/calendar/events",
        query=query,
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return ListEventsResponse.model_validate(payload)


@app.delete("/api/calendar/events/{event_id}")
def delete_event(event_id: str, req: DeleteEventRequest) -> JSONResponse:
    status_code, payload = _route_hecate(
        method="DELETE",
        path=f"/api/gateway/calendar/events/{event_id}",
        query={"provider": req.provider, "calendar_id": req.calendar_id},
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return JSONResponse(payload)


@app.patch("/api/calendar/events/{event_id}")
def update_event(event_id: str, req: UpdateEventRequest) -> JSONResponse:
    status_code, payload = _route_hecate(
        method="PUT",
        path=f"/api/gateway/calendar/events/{event_id}",
        body=req.model_dump(mode="json"),
        timeout_seconds=20,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return JSONResponse(payload)


@app.get("/api/calendar/providers")
def list_providers() -> dict:
    status_code, payload = _route_hecate(
        method="GET",
        path="/api/gateway/providers",
        timeout_seconds=10,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return payload


@app.post("/api/calendar/providers/{provider}/refresh")
def refresh_provider(provider: str) -> dict:
    status_code, payload = _route_hecate(
        method="POST",
        path=f"/api/gateway/auth/refresh/{provider}",
        body={},
        timeout_seconds=15,
    )
    if status_code >= 400:
        raise HTTPException(status_code=status_code, detail=payload)
    return payload


@app.get("/api/calendar/agenda")
def get_agenda(
    days: int = Query(
        7, ge=1, le=90, description="How many days ahead to look"),
    source: str | None = Query(
        None, description="Filter by source: google, outlook, hestia, …"),
    kind: str | None = Query(
        None, description="Filter by kind: event, task, reminder"),
) -> dict:
    """Return upcoming calendar items from Archive for the requested window.

    This endpoint is used by Telegram commands (``/agenda``, ``/agenda_oggi``)
    and by Oracle when the user asks about their schedule.
    """
    now = datetime.now(timezone.utc)
    to_time = now + timedelta(days=days)
    items = archive_client.list_items(
        from_time=now.isoformat(),
        to_time=to_time.isoformat(),
        source=source,
        kind=kind,
        limit=200,
    )
    return {
        "from": now.isoformat(),
        "to": to_time.isoformat(),
        "days": days,
        "count": len(items),
        "items": items,
    }


# ─────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("CALENDAR_PORT", "19007"))
    uvicorn.run("main:app", host="0.0.0.0", port=port,
                # WORKDIR=/code, flat imports
                reload=False, log_level=os.getenv("LOG_LEVEL", "INFO").lower())

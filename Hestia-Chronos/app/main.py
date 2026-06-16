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
from uuid import uuid4
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


class ModuleMaintenanceRequest(BaseModel):
    source: str = "oracle"
    task_id: str | None = None
    issue: str | None = None
    requested_action: str | None = "reconcile_calendar"
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

# ─────────────────────────────────────────────────────────────────────
#  App bootstrap
# ─────────────────────────────────────────────────────────────────────


app = FastAPI(title="Hestia Chronos", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────────────
#  MCP tools
# ─────────────────────────────────────────────────────────────────────

try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    _chronos_mcp_tools = [
        MCPTool(
            name="agenda",
            description="Mostra gli eventi in agenda nei prossimi 7 giorni",
            parameters={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "How many days ahead to look (default 7)"},
                    "source": {"type": "string", "description": "Filter by source: google, outlook, hestia, ..."},
                    "kind": {"type": "string", "description": "Filter by kind: event, task, reminder"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "agenda", "params": kw},
            title="\U0001f4c5 Agenda", method="GET", path="/api/calendar/agenda",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Mostra gli eventi dell'agenda in modo leggibile e cronologico. "
                "Per ogni evento indica titolo, data/ora, luogo (se presente) e "
                "una breve descrizione. Raggruppa per giorno. Usa un tono da "
                "assistente personale, amichevole e conciso."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_today",
            description="Mostra gli eventi di oggi",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_today", "params": kw},
            title="\U0001f4cb Agenda di oggi", method="GET", path="/api/calendar/agenda",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Mostra gli eventi di oggi in modo conciso. Se non ci sono "
                "eventi, dillo chiaramente. Usa linguaggio da assistente personale."
            ),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="create_event",
            description="Crea un nuovo evento nel calendario connesso (Google Calendar, Outlook). Usa per: crea evento, aggiungi appuntamento, imposta promemoria, pianifica riunione.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titolo o nome dell'evento"},
                    "start_datetime": {"type": "string", "description": "Data e ora di inizio nel formato ISO 8601 (YYYY-MM-DDTHH:MM:SS)"},
                    "end_datetime": {"type": "string", "description": "Data e ora di fine nel formato ISO 8601"},
                    "description": {"type": "string", "description": "Descrizione o note aggiuntive dell'evento"},
                    "location": {"type": "string", "description": "Luogo fisico o virtuale dell'evento"},
                },
                "required": ["title", "start_datetime"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "create_event", "params": kw},
            title="\U0001f4c5 Crea evento", method="POST", path="/api/calendar/events",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Conferma la creazione dell'evento con un messaggio breve e naturale. "
                "Includi titolo, data/ora di inizio. Se il provider ha restituito un link o ID, menzionalo. "
                "Usa un tono diretto e amichevole."
            ),
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="calendar_list_events",
            description="Elenca gli eventi in un intervallo temporale per provider calendario.",
            parameters={
                "type": "object",
                "properties": {
                    "start_datetime": {"type": "string", "description": "Inizio intervallo ISO 8601"},
                    "end_datetime": {"type": "string", "description": "Fine intervallo ISO 8601"},
                    "target_providers": {"type": "array", "items": {"type": "string"}, "description": "Provider destinazione"},
                    "calendar_id": {"type": "string", "description": "ID calendario"},
                    "max_results": {"type": "integer", "description": "Numero massimo risultati"},
                },
                "required": ["start_datetime", "end_datetime"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_list_events", "params": kw},
            title="\U0001f4c6 Elenca eventi", method="POST", path="/api/calendar/events/list",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="calendar_create_event",
            description="Crea un evento calendario con payload completo.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titolo evento"},
                    "start_datetime": {"type": "string", "description": "Data/ora inizio ISO 8601"},
                    "end_datetime": {"type": "string", "description": "Data/ora fine ISO 8601"},
                    "description": {"type": "string", "description": "Descrizione"},
                    "location": {"type": "string", "description": "Luogo"},
                    "provider": {"type": "string", "description": "Provider calendario (google, outlook)"},
                    "calendar_id": {"type": "string", "description": "ID calendario"},
                },
                "required": ["title", "start_datetime"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_create_event", "params": kw},
            title="\U0001f4c5 Crea evento calendario", method="POST", path="/api/calendar/events",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="calendar_update_event",
            description="Aggiorna campi di un evento calendario esistente.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "ID evento"},
                    "provider": {"type": "string", "description": "Provider calendario"},
                    "calendar_id": {"type": "string", "description": "ID calendario"},
                    "updates": {"type": "object", "description": "Campi da aggiornare"},
                },
                "required": ["event_id", "provider"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_update_event", "params": kw},
            title="✏️ Aggiorna evento calendario", method="PATCH", path="/api/calendar/events/$arg.event_id",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="calendar_delete_event",
            description="Elimina un evento calendario esistente.",
            parameters={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "description": "ID evento"},
                    "provider": {"type": "string", "description": "Provider calendario"},
                    "calendar_id": {"type": "string", "description": "ID calendario"},
                },
                "required": ["event_id", "provider"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "calendar_delete_event", "params": kw},
            title="\U0001f5d1️ Elimina evento calendario", method="DELETE", path="/api/calendar/events/$arg.event_id",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="chronos_reconcile",
            description="Esegue manutenzione di riconciliazione nel modulo Chronos",
            parameters={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "Se true esegue solo simulazione senza avviare i worker tick"},
                    "requested_action": {"type": "string", "description": "Azione opzionale: reconcile_calendar|sync|notify|full"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "chronos_reconcile", "params": kw},
            title="\U0001f6e0️ Riconcilia calendario", method="POST", path="/api/module/maintenance/reconcile",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Riassumi l'esito della riconciliazione Chronos, indicando quali tick sono stati eseguiti e se era dry-run.",
            telegram_visible=True, telegram_group="pianificazione",
        ),
    ]
    app.include_router(create_mcp_router(_chronos_mcp_tools, service_name="chronos"))
    logger.info("event=mcp_router_mounted service=chronos")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=chronos reason=hestia_common_not_available")

# ─────────────────────────────────────────────────────────────────────


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


@app.post("/api/module/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def module_maintenance_reconcile(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    task_id = str(req.task_id or uuid4())
    action = str(req.requested_action or "reconcile_calendar").strip().lower()

    if req.dry_run:
        return ModuleMaintenanceResponse(
            status="ok",
            service="chronos",
            dry_run=True,
            task_id=task_id,
            executed_at=datetime.now(timezone.utc),
            retriable=True,
            summary="Chronos maintenance dry-run accepted: no worker ticks executed.",
            mutation_count=0,
            details={
                "requested_action": action,
                "note": "Set dry_run=false to execute maintenance tick(s).",
            },
        )

    tick_results: dict[str, str] = {}
    mutation_count = 0

    if action in {"reconcile_calendar", "sync", "sync_tick", "full"}:
        try:
            sync_worker._tick()  # pylint: disable=protected-access
            tick_results["sync"] = "ok"
            mutation_count += 1
        except Exception as error:
            tick_results["sync"] = f"error:{error}"

    if action in {"reconcile_calendar", "notify", "notify_tick", "full"}:
        try:
            notification_worker._tick()  # pylint: disable=protected-access
            tick_results["notify"] = "ok"
            mutation_count += 1
        except Exception as error:
            tick_results["notify"] = f"error:{error}"

    if not tick_results:
        tick_results["noop"] = "unsupported_requested_action"

    return ModuleMaintenanceResponse(
        status="ok",
        service="chronos",
        dry_run=False,
        task_id=task_id,
        executed_at=datetime.now(timezone.utc),
        retriable=True,
        summary="Chronos maintenance reconcile executed.",
        mutation_count=mutation_count,
        details={
            "requested_action": action,
            "ticks": tick_results,
        },
    )


@app.post("/api/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def maintenance_reconcile_alias(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    return module_maintenance_reconcile(req)


# ─────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("CALENDAR_PORT", "19007"))
    uvicorn.run("main:app", host="0.0.0.0", port=port,
                # WORKDIR=/code, flat imports
                reload=False, log_level=os.getenv("LOG_LEVEL", "INFO").lower())

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
from fastapi.responses import JSONResponse, Response
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
from services import agenda as assistant_agenda
from services import agenda_parse
from services import notification_worker, sync_worker
from services import presence as assistant_presence
from core import presence_settings

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
        MCPTool(
            name="agenda_assistente",
            description=(
                "Agenda di Hestia stessa (NON il calendario dell'utente): cosa l'assistente e i suoi moduli "
                "hanno pianificato — finestre (es. Claude Pro di notte), job periodici, task di riparazione, eventi."
            ),
            parameters={"type": "object", "properties": {
                "days": {"type": "integer", "description": "giorni avanti (default 7)"},
                "owner": {"type": "string", "description": "modulo: hephaestus, scout, athena..."}}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente", "params": kw},
            title="\U0001f916 Agenda di Hestia", method="GET", path="/api/agenda",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=("Elenco cronologico raggruppato per giorno: ora, titolo, modulo. "
                             "Segna le occorrenze saltate. Niente JSON. Mostra l'id tra parentesi."),
            telegram_visible=True, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_aggiungi",
            description="Aggiunge alla agenda di Hestia un evento/task/finestra/job (on demand)",
            parameters={"type": "object", "properties": {
                "title": {"type": "string", "description": "titolo"},
                "type": {"type": "string", "description": "event | task | job | window"},
                "start_at": {"type": "string", "description": "inizio ISO 8601"},
                "end_at": {"type": "string", "description": "fine ISO (obbligatoria per window)"},
                "recurrence": {"type": "string", "description": "RRULE se periodico, es. FREQ=WEEKLY;BYDAY=SA"},
                "description": {"type": "string", "description": "dettagli"},
                "parent": {"type": "string", "description": "chiave voce collegata (annullo a cascata)"}},
                "required": ["title", "start_at"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_aggiungi", "params": kw},
            title="\u2795 Pianifica per Hestia", method="POST", path="/api/agenda/items",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_sposta",
            description="Sposta/modifica una voce dell'agenda di Hestia (nuovo orario, ricorrenza, pausa)",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce"},
                "start_at": {"type": "string", "description": "nuovo inizio ISO"},
                "end_at": {"type": "string", "description": "nuova fine ISO"},
                "recurrence": {"type": "string", "description": "nuova RRULE"},
                "status": {"type": "string", "description": "confirmed | paused"}},
                "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_sposta", "params": kw},
            title="\U0001f501 Sposta voce agenda Hestia", method="PATCH", path="/api/agenda/items/{ref}",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_salta",
            description="Salta (dismiss) la prossima occorrenza di una voce dell'agenda di Hestia, senza cancellare la regola",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce"},
                "occurrence": {"type": "string", "description": "occorrenza ISO (vuoto = prossima)"}},
                "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_salta", "params": kw},
            title="\u23ed\ufe0f Salta occorrenza", method="POST", path="/api/agenda/items/{ref}/skip",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_ripristina",
            description="Ripristina un'occorrenza saltata di una voce dell'agenda di Hestia",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce"},
                "occurrence": {"type": "string", "description": "occorrenza ISO saltata"}},
                "required": ["ref", "occurrence"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_ripristina", "params": kw},
            title="\u21a9\ufe0f Ripristina occorrenza", method="POST", path="/api/agenda/items/{ref}/unskip",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_sposta_occorrenza",
            description=("Sposta SOLO un'occorrenza di una voce ricorrente (eccezione, come 'solo questo evento'); "
                         "reset=true la riporta all'orario originale"),
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce"},
                "occurrence": {"type": "string", "description": "occorrenza ISO originale"},
                "start_at": {"type": "string", "description": "nuovo inizio ISO"},
                "end_at": {"type": "string", "description": "nuova fine ISO"},
                "reset": {"type": "boolean", "description": "ripristina orario originale"}},
                "required": ["ref", "occurrence"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_sposta_occorrenza", "params": kw},
            title="\U0001f4cd Sposta una occorrenza", method="POST", path="/api/agenda/items/{ref}/move",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_modelli",
            description=("Modelli che i moduli offrono per creare voci (es. Scout: ricerca immobili periodica). "
                         "Usalo prima di agenda_assistente_da_modello"),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_modelli", "params": kw},
            title="\U0001f9e9 Modelli agenda", method="GET", path="/api/agenda/templates",
            clients=["ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_da_modello",
            description="Crea una voce dell'agenda di Hestia da un modello di un modulo (campi in values)",
            parameters={"type": "object", "properties": {
                "owner": {"type": "string", "description": "modulo del modello"},
                "template_id": {"type": "string", "description": "id modello"},
                "values": {"type": "object", "description": "campi del modello"},
                "start_at": {"type": "string", "description": "inizio ISO"},
                "end_at": {"type": "string", "description": "fine ISO (finestre)"},
                "recurrence": {"type": "string", "description": "RRULE se periodico"}},
                "required": ["owner", "template_id", "start_at"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_da_modello", "params": kw},
            title="\U0001f9e9 Crea da modello", method="POST", path="/api/agenda/templates/{owner}/{template_id}/create",
            clients=["ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_collega",
            description="Collega una voce a una voce padre: annullare il padre annulla la figlia, l'errore della figlia segna il padre",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce figlia"},
                "parent": {"type": "string", "description": "chiave del padre (vuoto = scollega)"}},
                "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_collega", "params": kw},
            title="\U0001f517 Collega voci agenda", method="POST", path="/api/agenda/items/{ref}/link",
            clients=["ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_annulla",
            description="Annulla definitivamente una voce dell'agenda di Hestia",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce"}}, "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_annulla", "params": kw},
            title="\U0001f5d1\ufe0f Annulla voce agenda Hestia", method="DELETE", path="/api/agenda/items/{ref}",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="agenda_assistente_esegui",
            description="Esegue subito l'azione di un job/task dell'agenda di Hestia",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "id o chiave della voce"}}, "required": ["ref"]},
            handler=lambda **kw: {"status": "ok", "tool": "agenda_assistente_esegui", "params": kw},
            title="\u25b6\ufe0f Esegui ora", method="POST", path="/api/agenda/items/{ref}/run",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=False, telegram_group="pianificazione",
        ),
        MCPTool(
            name="stato",
            description=("Stato di attività dell'assistente: sveglio, in attesa, pisolino, sonno profondo, "
                         "non disturbare (+ occupato/stanco…), ultima interazione, lavori in corso ed effetti "
                         "(cosa è permesso ora). Usalo quando l'utente chiede come stai, cosa stai facendo, "
                         "da quanto non vi sentite."),
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "stato", "params": kw},
            title="\U0001f9ed Stato dell'assistente", method="GET", path="/api/presence",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt=(
                "Descrivi in 2-4 righe lo stato dell'assistente in prima persona: label con emoji, da quando, "
                "ultima interazione (client e quanto tempo fa), lavori in corso (activities) e, se rilevante, "
                "cosa rimando (effects con defer/save). Niente JSON, niente chiavi tecniche."),
            telegram_visible=True, telegram_group="sistema",
        ),
        MCPTool(
            name="nondisturbare",
            description=("Attiva «Non disturbare»: passano solo le notifiche urgenti. minutes = durata "
                         "(vuoto = predefinita), until = fino a un orario ISO 8601."),
            parameters={"type": "object", "properties": {
                "minutes": {"type": "integer", "description": "Durata in minuti (vuoto = predefinita)"},
                "until": {"type": "string", "description": "Fino a quando, ISO 8601"}}},
            handler=lambda **kw: {"status": "ok", "tool": "nondisturbare", "params": kw},
            title="\U0001f515 Non disturbare", method="POST", path="/api/presence/dnd",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Conferma in una riga che «Non disturbare» è attivo e fino a che ora (dnd_until, ora locale).",
            telegram_visible=True, telegram_group="sistema",
        ),
        MCPTool(
            name="disturbami",
            description="Disattiva «Non disturbare».",
            parameters={"type": "object", "properties": {}},
            handler=lambda **kw: {"status": "ok", "tool": "disturbami", "params": kw},
            title="\U0001f514 Disattiva non disturbare", method="DELETE", path="/api/presence/dnd",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Conferma in una riga che «Non disturbare» è spento e indica il nuovo stato (label).",
            telegram_visible=True, telegram_group="sistema",
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
    assistant_agenda.start_worker()
    # Assistant presence (SPEC assistant-presence): settings from Themis, state from Archive,
    # night window in the agenda, re-evaluated after every agenda tick.
    presence_settings.settings.on_change(lambda changed: assistant_presence.get_engine().evaluate("settings"))
    presence_settings.settings.start()
    threading.Thread(target=_presence_boot, daemon=True, name="presence-boot").start()
    assistant_agenda.on_tick(lambda: assistant_presence.get_engine().evaluate("tick"))


def _presence_boot() -> None:
    """Load signals/snapshot and register the night window (retry: never block startup)."""
    from hestia_common.agenda_client import daily_window
    engine, loaded, registered = assistant_presence.get_engine(), False, False
    for attempt in range(30):
        loaded = loaded or engine.load()
        if not registered:
            try:
                assistant_agenda.register_rules("chronos", [daily_window(
                    presence_settings.SLEEP_WINDOW, "Hestia: notte (sonno profondo)", 1, 7,
                    description="Di notte l'assistente va in sonno profondo: lavori pesanti permessi, "
                                "solo notifiche urgenti. Sposta o salta per cambiare la notte.")])
                registered = True
            except Exception as exc:
                logger.warning("[🔄] event=presence_window_register_failed attempt=%d error=%s", attempt + 1, exc)
        if loaded and registered:
            break
        time.sleep(min(60, 5 * (attempt + 1)))
    engine.evaluate("boot")


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

app.include_router(create_log_control_router("hestia_chronos"))
app.include_router(presence_settings.settings.router())

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
    # Window starts at local midnight: "agenda di oggi" used to start at "now",
    # hiding events already started today and all-day events (stored 00:00).
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(os.getenv("CHRONOS_DISPLAY_TZ") or os.getenv("TZ") or "Europe/Rome")
    now = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    to_time = now + timedelta(days=days)
    items = archive_client.list_items(
        from_time=now.isoformat(),
        to_time=to_time.isoformat(),
        source=source,
        kind=kind,
        limit=200,
    )
    if not source:
        # The assistant's own agenda (source=hestia) is not part of the user's calendar.
        items = [i for i in items if i.get("source") != assistant_agenda.SOURCE]
    return {
        "from": now.isoformat(),
        "to": to_time.isoformat(),
        "days": days,
        "count": len(items),
        "items": items,
    }


# ─────────────────────────────────────────────────────────────────────
#  Assistant agenda (Hestia's own calendar, source=hestia)
# ─────────────────────────────────────────────────────────────────────


class CalendarSyncRequest(BaseModel):
    trigger: str = "api"


@app.post("/api/calendar/sync")
def calendar_sync(req: CalendarSyncRequest | None = None) -> dict:
    """Run a calendar sync now in background (agenda job ``chronos.calendar_sync``)."""
    trigger = (req or CalendarSyncRequest()).trigger
    threading.Thread(target=sync_worker.run_sync, args=(trigger,), daemon=True,
                     name="chronos-sync-run").start()
    return {"status": "started", "trigger": trigger, "agenda_job": sync_worker.AGENDA_JOB_KEY}


class AgendaAction(BaseModel):
    service: str
    path: str
    method: str = "POST"
    body: dict | None = None
    query: dict | None = None
    timeout_seconds: float = 30


class AgendaItemCreate(BaseModel):
    title: str
    type: str = Field("event", description="event | task | job | window")
    owner: str = "user"
    start_at: str
    end_at: str | None = None
    recurrence: str | None = Field(None, description="RRULE, e.g. FREQ=DAILY;BYHOUR=3")
    description: str | None = None
    action: AgendaAction | None = None
    key: str | None = None
    params: dict = Field(default_factory=dict)
    tz: str | None = None
    created_by: str = "user"
    parent: str | None = Field(None, description="key of the linked parent item (cascade cancel / error)")


class AgendaItemChange(BaseModel):
    title: str | None = None
    description: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    recurrence: str | None = None
    status: str | None = Field(None, description="confirmed | paused | cancelled")
    action: AgendaAction | None = None
    params: dict | None = None
    by: str = "user"


class AgendaRegister(BaseModel):
    owner: str
    rules: list[dict]


class AgendaSkip(BaseModel):
    occurrence: str | None = None
    by: str = "user"


def _agenda_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except assistant_agenda.AgendaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/agenda")
def agenda_view(days: int = Query(7, ge=1, le=400), owner: str | None = None, type: str | None = None,
                past_hours: int = Query(0, ge=0, le=24 * 400),
                start: str | None = Query(None, description="ISO start (overrides days/past_hours)"),
                end: str | None = Query(None, description="ISO end (with start)"),
                include_done: bool = Query(False, description="also completed/cancelled items")) -> dict:
    """Assistant agenda occurrences (windows, jobs, tasks, events).

    Range: ``start``/``end`` (ISO, used by the WebUI calendar) or now-``past_hours`` → now+``days``.
    """
    now = datetime.now(timezone.utc)
    if start:
        try:
            lo = datetime.fromisoformat(start.replace("Z", "+00:00"))
            hi = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else lo + timedelta(days=days)
        except ValueError:
            raise HTTPException(status_code=400, detail="start/end must be ISO datetimes")
        if lo.tzinfo is None:
            lo = lo.replace(tzinfo=timezone.utc)
        if hi.tzinfo is None:
            hi = hi.replace(tzinfo=timezone.utc)
        if hi <= lo or (hi - lo).days > 400:
            raise HTTPException(status_code=400, detail="end must be after start, range <= 400 days")
    else:
        lo, hi = now - timedelta(hours=past_hours), now + timedelta(days=days)
    rows = assistant_agenda.agenda(lo, hi, owner=owner, type_=type, include_done=include_done)
    return {"from": lo.isoformat(), "to": hi.isoformat(), "days": days,
            "count": len(rows), "occurrences": rows}


@app.get("/api/agenda/items")
def agenda_items(owner: str | None = None, type: str | None = None, include_cancelled: bool = False) -> dict:
    items = assistant_agenda.list_items(owner=owner, type_=type, include_cancelled=include_cancelled)
    return {"count": len(items), "items": items}


@app.post("/api/agenda/items")
def agenda_create(req: AgendaItemCreate) -> dict:
    data = req.model_dump()
    item = _agenda_guard(
        assistant_agenda.create, title=data["title"], type_=data["type"], owner=data["owner"],
        start_at=data["start_at"], end_at=data["end_at"], recurrence=data["recurrence"],
        description=data["description"], action=data["action"], key=data["key"],
        params=data["params"], tz=data["tz"], created_by=data["created_by"], parent=data["parent"])
    return {"status": "ok", "item": item}


@app.post("/api/agenda/register")
def agenda_register(req: AgendaRegister) -> dict:
    """Modules declare their default rules (idempotent; user edits are preserved)."""
    items = _agenda_guard(assistant_agenda.register_rules, req.owner, req.rules)
    return {"status": "ok", "count": len(items), "items": items}


@app.patch("/api/agenda/items/{ref}")
def agenda_update(ref: str, req: AgendaItemChange) -> dict:
    changes = req.model_dump(exclude={"by"}, exclude_none=True)
    if changes.get("status") == "cancelled":
        changes.pop("status")
        if changes:
            _agenda_guard(assistant_agenda.update, ref, changes, req.by)
        return {"status": "ok", "item": _agenda_guard(assistant_agenda.cancel, ref, req.by)}  # cascade
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.update, ref, changes, req.by)}


@app.delete("/api/agenda/items/{ref}")
def agenda_cancel(ref: str, by: str = "user") -> dict:
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.cancel, ref, by)}


@app.post("/api/agenda/items/{ref}/skip")
def agenda_skip(ref: str, req: AgendaSkip | None = None) -> dict:
    r = req or AgendaSkip()
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.skip, ref, r.occurrence, r.by)}


@app.post("/api/agenda/items/{ref}/unskip")
def agenda_unskip(ref: str, req: AgendaSkip) -> dict:
    if not req.occurrence:
        raise HTTPException(status_code=400, detail="occurrence required")
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.unskip, ref, req.occurrence, req.by)}


class AgendaMove(BaseModel):
    occurrence: str
    start_at: str | None = None
    end_at: str | None = None
    reset: bool = False
    by: str = "user"


@app.post("/api/agenda/items/{ref}/move")
def agenda_move(ref: str, req: AgendaMove) -> dict:
    """Move one occurrence only (exception); ``reset`` restores it. One-off items move entirely."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.move_occurrence, ref, req.occurrence,
                                                  req.start_at, req.end_at, req.reset, req.by)}


class AgendaLink(BaseModel):
    parent: str | None = Field(None, description="parent key; empty clears the link")
    by: str = "user"


class AgendaFail(BaseModel):
    detail: str = ""
    by: str = "module"


@app.get("/api/agenda/items/{ref}/links")
def agenda_links(ref: str) -> dict:
    item = _agenda_guard(assistant_agenda.get, ref)
    parent = None
    if item.get("parent"):
        try:
            parent = assistant_agenda.get(item["parent"])
        except assistant_agenda.AgendaError:
            parent = None
    return {"status": "ok", "key": item["key"], "parent": parent,
            "children": assistant_agenda.children(item["key"])}


@app.post("/api/agenda/items/{ref}/link")
def agenda_link(ref: str, req: AgendaLink) -> dict:
    """Link an item to a parent: cancelling the parent cancels it; its failure marks the parent."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.link, ref, req.parent, req.by)}


@app.post("/api/agenda/items/{ref}/fail")
def agenda_fail(ref: str, req: AgendaFail) -> dict:
    """A module reports that the work behind the item failed (propagates to the parent)."""
    return {"status": "ok", "item": _agenda_guard(assistant_agenda.fail, ref, req.detail, req.by)}


@app.post("/api/agenda/items/{ref}/run")
def agenda_run(ref: str) -> dict:
    return {"status": "ok", **_agenda_guard(assistant_agenda.run_now, ref)}


class AgendaTemplates(BaseModel):
    owner: str
    templates: list[dict] = []


class AgendaFromTemplate(BaseModel):
    values: dict = {}
    start_at: str
    end_at: str | None = None
    recurrence: str | None = None
    type: str | None = None
    description: str | None = None


@app.post("/api/agenda/templates")
def agenda_templates_register(req: AgendaTemplates) -> dict:
    """Modules declare what the user can create for them (calendar wizard). Replaces the owner's set."""
    return {"status": "ok", "count": assistant_agenda.register_templates(req.owner, req.templates)}


@app.get("/api/agenda/templates")
def agenda_templates() -> dict:
    rows = assistant_agenda.list_templates()
    return {"count": len(rows), "templates": rows}


@app.post("/api/agenda/templates/{owner}/{template_id}/create")
def agenda_from_template(owner: str, template_id: str, req: AgendaFromTemplate) -> dict:
    item = _agenda_guard(assistant_agenda.create_from_template, owner, template_id, values=req.values,
                         start_at=req.start_at, end_at=req.end_at, recurrence=req.recurrence,
                         type_=req.type, description=req.description)
    return {"status": "ok", "item": item}


class AgendaParse(BaseModel):
    text: str
    tz: str | None = None


@app.post("/api/agenda/parse")
def agenda_parse_text(req: AgendaParse) -> dict:
    """Natural-language quick add: draft fields for the editor (nothing is created)."""
    try:
        return {"status": "ok", "draft": agenda_parse.parse(req.text, tz_name=req.tz)}
    except agenda_parse.ParseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@app.get("/api/agenda/ics")
def agenda_ics(days: int = Query(60, ge=1, le=400), past_days: int = Query(7, ge=0, le=90),
               owner: str | None = None,
               types: str = Query("event,task,window", description="comma list; add job for periodic jobs")) -> Response:
    """Read-only iCalendar feed of the assistant agenda (expanded occurrences, skips/moves applied)."""
    now = datetime.now(timezone.utc)
    wanted = {t.strip() for t in types.split(",") if t.strip()}
    rows = [o for o in assistant_agenda.agenda(now - timedelta(days=past_days), now + timedelta(days=days), owner=owner)
            if o.get("type") in wanted][:3000]
    return Response(agenda_parse.to_ics(rows), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'inline; filename="hestia-agenda.ics"'})


@app.get("/api/agenda/windows/{key}")
def agenda_window(key: str) -> dict:
    """Modules ask: is my window open now? (closed if missing/cancelled/skipped)."""
    return {"status": "ok", **assistant_agenda.window_status(key)}


# ─────────────────────────────────────────────────────────────────────
#  Assistant presence (SPEC docs/work/2026-10-10-assistant-presence)
# ─────────────────────────────────────────────────────────────────────


class PresencePing(BaseModel):
    client: str = "unknown"
    kind: str = "chat"          # chat | command | ui


class PresenceActivity(BaseModel):
    key: str
    label: str = ""
    load: str = "light"         # light | heavy
    resource: str = ""          # gpu | claude_quota | cpu …
    kind: str = "work"          # work | maintenance
    module: str = ""
    ttl_seconds: float = 3600


class PresenceSignalIn(BaseModel):
    value: Any = True
    meta: dict | None = None
    ttl_seconds: float | None = None


class PresenceDnd(BaseModel):
    minutes: float | None = None
    until: str | None = None


class PresenceStates(BaseModel):
    owner: str
    states: dict[str, dict] = Field(default_factory=dict)


def _presence_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/presence")
def presence_view() -> dict:
    """Current state: base + overlays, label, effects, last interaction, activities."""
    return assistant_presence.get_engine().view()


@app.post("/api/presence/ping")
def presence_ping(req: PresencePing | None = None) -> dict:
    req = req or PresencePing()
    return assistant_presence.get_engine().ping(req.client, req.kind)


@app.post("/api/presence/activity")
def presence_activity_start(req: PresenceActivity) -> dict:
    return _presence_guard(assistant_presence.get_engine().activity_start, req.key, label=req.label,
                           load=req.load, resource=req.resource, kind=req.kind, module=req.module,
                           ttl=req.ttl_seconds)


@app.delete("/api/presence/activity/{key}")
def presence_activity_stop(key: str) -> dict:
    return assistant_presence.get_engine().activity_stop(key)


@app.put("/api/presence/signals/{key}")
def presence_signal_set(key: str, req: PresenceSignalIn) -> dict:
    """Generic fact (e.g. ``resource.claude_quota_left``, ``health.degraded_services``)."""
    return _presence_guard(assistant_presence.get_engine().set_signal, key, req.value, meta=req.meta,
                           ttl=req.ttl_seconds)


@app.delete("/api/presence/signals/{key}")
def presence_signal_clear(key: str) -> dict:
    return assistant_presence.get_engine().clear_signal(key)


@app.post("/api/presence/dnd")
def presence_dnd_on(req: PresenceDnd | None = None) -> dict:
    req = req or PresenceDnd()
    return assistant_presence.get_engine().set_dnd(minutes=req.minutes, until=req.until)


@app.delete("/api/presence/dnd")
def presence_dnd_off() -> dict:
    return assistant_presence.get_engine().clear_dnd()


@app.get("/api/presence/states")
def presence_states() -> dict:
    """Effective definitions (built-in + modules + the user's setting); edits go through Themis."""
    return {"setting": presence_settings.STATES, "core": list(presence_settings.CORE_STATES),
            "effects": presence_settings.EFFECT_ORDER, "states": assistant_presence.get_engine().states()}


@app.post("/api/presence/states/register")
def presence_states_register(req: PresenceStates) -> dict:
    """A module declares its own states (in memory, re-asserted by the module)."""
    count = assistant_presence.get_engine().declare_states(req.owner, req.states)
    return {"status": "ok", "owner": req.owner, "count": count}


@app.get("/api/presence/history")
def presence_history(limit: int = Query(50, ge=1, le=500)) -> dict:
    rows = assistant_presence.get_engine().history(limit)
    return {"count": len(rows), "items": rows}


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
            result = sync_worker.run_sync("maintenance")
            tick_results["sync"] = result["status"] if result["status"] != "error" else f"error:{result.get('error')}"
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

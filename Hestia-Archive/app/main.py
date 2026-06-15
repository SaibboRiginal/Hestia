"""Hestia Archive — FastAPI application entry point.

Single responsibility: bootstrap the app (database setup, Hub registration)
and wire in the domain routers. All endpoint logic lives in app/routers/.
"""
import logging
import os
from pathlib import Path
import sys

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from . import models, database
from .database import engine
from .routers import archive, chat, calendar, documents, entities, memory

try:
    from hestia_common.logging_utils import log_event, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import log_event, setup_service_logging

logger, log_buffer = setup_service_logging("hestia_archive")

# ── Database bootstrap ────────────────────────────────────────────────────────
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

models.Base.metadata.create_all(bind=engine)

# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(title="Hestia-Archive Vault",
              version="3.0.0 (Entity & Vector Ready)")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])

# Include all domain routers
app.include_router(archive.router)
app.include_router(entities.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(calendar.router)
app.include_router(documents.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_archive"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    return {
        "service": "hestia_archive",
        "count": len(log_buffer.query(limit=limit, level=level, contains=contains)),
        "logs": log_buffer.query(limit=limit, level=level, contains=contains),
    }


# ── Hub registration ──────────────────────────────────────────────────────────
_HUB_REGISTRATION_PAYLOAD = {
    "name": "archive",
    "base_url": os.getenv("ARCHIVE_SERVICE_BASE_URL", "http://hestia_archive:19002"),
    "health_endpoint": "/health",
    "service_type": "core",
    "service_version": os.getenv("ARCHIVE_SERVICE_VERSION", "1.0.0"),
    "tags": ["core", "storage"],
    "topology_tags": ["layer:foundation", "domain:storage", "status:stable"],
    "capabilities": {
        "api_prefix": "/api",
        "commands": [
            {
                "command": "preferenze_attive",
                "title": "🧠 Preferenze attive",
                "description": "Mostra le preferenze utente attive",
                "method": "GET",
                "path": "/api/memory/active",
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Mostra le preferenze attive in elenco sintetico, raggruppando per dominio e usando linguaggio naturale.",
            },
            {
                "command": "notifiche_attive",
                "title": "🔔 Notifiche attive",
                "description": "Mostra le notifiche automatiche attive",
                "method": "GET",
                "path": "/api/subscriptions/active",
                "clients": ["telegram", "ui"],
                "response_mode": "raw_json",
            },
            {
                "command": "avvisi_recenti",
                "title": "📬 Avvisi recenti",
                "description": "Mostra gli ultimi avvisi inviati",
                "method": "GET",
                "path": "/api/dispatch/logs/enriched",
                "query_template": {"limit": 15, "hours": 72},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Mostra una timeline degli avvisi recenti con TITOLO COMPLETO della proprietà, indirizzo, prezzo e data/ora. Usa link leggibili con il titolo dell'immobile, NON 'Apri annuncio'. Per ogni avviso indica se è stato consegnato con successo. Sii conciso ma informativo.",
            },
            {
                "command": "notifica_disattiva",
                "title": "🔕 Disattiva notifica",
                "description": "Disattiva una notifica tramite subscription_id",
                "method": "PATCH",
                "path": "/api/subscriptions/$arg.subscription_id/active",
                "body_template": {"is_active": False},
                "arguments_help": "subscription_id=<id>",
                "arg_picker": {
                    "arg": "subscription_id",
                    "source": {
                        "service": "archive",
                        "method": "GET",
                        "path": "/api/subscriptions/active",
                    },
                    "value_field": "subscription_id",
                    "label_fields": ["domain", "event_type", "filters"],
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma chiaramente l'avvenuta disattivazione della notifica.",
            },
            {
                "command": "notifica_attiva",
                "title": "🔔 Riattiva notifica",
                "description": "Riattiva una notifica tramite subscription_id",
                "method": "PATCH",
                "path": "/api/subscriptions/$arg.subscription_id/active",
                "body_template": {"is_active": True},
                "arguments_help": "subscription_id=<id>",
                "arg_picker": {
                    "arg": "subscription_id",
                    "source": {
                        "service": "archive",
                        "method": "GET",
                        "path": "/api/subscriptions/active",
                    },
                    "value_field": "subscription_id",
                    "label_fields": ["domain", "event_type", "filters"],
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma chiaramente l'avvenuta riattivazione della notifica.",
            },
            # ── Calendar reminder subscriptions ───────────────────────────────
            {
                "command": "iscriviti_calendario",
                "title": "📅 Attiva promemoria calendario",
                "description": "Ricevi promemoria automatici per eventi del calendario",
                "method": "POST",
                "path": "/api/subscriptions",
                "body_template": {
                    "subscription_id": "cal-reminder-$chat_id",
                    "owner": "$chat_id",
                    "domain": "calendar",
                    "event_type": "calendar.reminder",
                    "filters": {},
                    "channels": [{"type": "telegram", "target": "$chat_id"}],
                    "is_active": True,
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma brevemente l'attivazione dei promemoria calendario.",
            },
            {
                "command": "disiscriviti_calendario",
                "title": "📅 Disattiva promemoria calendario",
                "description": "Smetti di ricevere promemoria automatici del calendario",
                "method": "PATCH",
                "path": "/api/subscriptions/cal-reminder-$chat_id/active",
                "body_template": {"is_active": False},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma brevemente la disattivazione dei promemoria calendario.",
            },
            # ── System health alert subscriptions ─────────────────────────────
            {
                "command": "iscriviti_sistema",
                "title": "🔧 Attiva allerte sistema",
                "description": "Ricevi notifiche sullo stato dei servizi Hestia",
                "method": "POST",
                "path": "/api/subscriptions",
                "body_template": {
                    "subscription_id": "sys-health-$chat_id",
                    "owner": "$chat_id",
                    "domain": "system",
                    "event_type": "service.health",
                    "filters": {},
                    "channels": [{"type": "telegram", "target": "$chat_id"}],
                    "is_active": True,
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma brevemente l'attivazione delle allerte di sistema.",
            },
            {
                "command": "disiscriviti_sistema",
                "title": "🔧 Disattiva allerte sistema",
                "description": "Smetti di ricevere notifiche sullo stato dei servizi Hestia",
                "method": "PATCH",
                "path": "/api/subscriptions/sys-health-$chat_id/active",
                "body_template": {"is_active": False},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma brevemente la disattivazione delle allerte di sistema.",
            },
            {
                "command": "archive_reconcile",
                "title": "🛠️ Riconcilia archivio",
                "description": "Esegue una manutenzione di riconciliazione sui record entita in Archive",
                "method": "POST",
                "path": "/api/module/maintenance/reconcile",
                "body_template": {
                    "source": "oracle",
                    "requested_action": "reconcile_entities",
                    "dry_run": True,
                    "metadata": {},
                },
                "arguments_schema": {
                    "dry_run": {
                        "type": "boolean",
                        "required": False,
                        "description": "Se true esegue solo simulazione senza cancellazioni",
                    },
                    "domain": {
                        "type": "string",
                        "required": False,
                        "description": "Dominio opzionale su cui limitare la riconciliazione",
                    },
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Riassumi l'esito della riconciliazione includendo record analizzati, modifiche applicate e se l'esecuzione era dry-run.",
            },
        ],
    },
}


@app.on_event("startup")
def register_on_hub_startup():
    """Register this service with the Hub on startup (best-effort)."""
    hub_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    try:
        resp = requests.post(f"{hub_url}/registry/register",
                             json=_HUB_REGISTRATION_PAYLOAD, timeout=4)
        if resp.status_code < 400:
            log_event(
                logger,
                logging.INFO,
                "hub_register_success",
                service="archive",
                hub=hub_url,
                base_url=_HUB_REGISTRATION_PAYLOAD.get("base_url"),
                status_code=resp.status_code,
            )
        else:
            log_event(
                logger,
                logging.WARNING,
                "hub_register_non_success",
                service="archive",
                hub=hub_url,
                status_code=resp.status_code,
                body_preview=resp.text[:200],
            )
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "hub_register_exception",
            service="archive",
            hub=hub_url,
            error=str(exc),
        )

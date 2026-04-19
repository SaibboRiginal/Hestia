"""Hestia Archive — FastAPI application entry point.

Single responsibility: bootstrap the app (database setup, Hub registration)
and wire in the domain routers. All endpoint logic lives in app/routers/.
"""
import os

import requests
from fastapi import FastAPI
from sqlalchemy import text

from . import models, database
from .database import engine
from .routers import archive, chat, calendar, documents, entities, memory

# ── Database bootstrap ────────────────────────────────────────────────────────
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

models.Base.metadata.create_all(bind=engine)

# ── Application ───────────────────────────────────────────────────────────────
app = FastAPI(title="Hestia-Archive Vault", version="3.0.0 (Entity & Vector Ready)")

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


# ── Hub registration ──────────────────────────────────────────────────────────
_HUB_REGISTRATION_PAYLOAD = {
    "name": "archive",
    "base_url": os.getenv("ARCHIVE_SERVICE_BASE_URL", "http://hestia_archive:19002"),
    "health_endpoint": "/health",
    "service_type": "core",
    "service_version": os.getenv("ARCHIVE_SERVICE_VERSION", "1.0.0"),
    "tags": ["core", "storage"],
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
                "query_template": {"owner": "$session_id"},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Mostra le notifiche attive con filtri principali, stato e cosa verrà notificato, in modo leggibile e breve.",
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
                        "query_template": {"owner": "$session_id"},
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
                        "query_template": {"owner": "$session_id"},
                    },
                    "value_field": "subscription_id",
                    "label_fields": ["domain", "event_type", "filters"],
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Conferma chiaramente l'avvenuta riattivazione della notifica.",
            },
        ],
    },
}


@app.on_event("startup")
def register_on_hub_startup():
    """Register this service with the Hub on startup (best-effort)."""
    hub_url = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    try:
        requests.post(f"{hub_url}/registry/register", json=_HUB_REGISTRATION_PAYLOAD, timeout=4)
    except Exception:
        pass

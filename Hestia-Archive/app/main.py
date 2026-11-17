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

from . import models, database, schema, schemas
from .database import engine, SessionLocal
from .routers import archive, blobs, chat, chat_queue, calendar, documents, entities, hercules_store, llm_usage_store, mcp_access_store, memory, module_store, presence, selfcare_store, settings, wardrobe_store

try:
    from hestia_common.logging_utils import create_log_control_router, log_event, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, log_event, setup_service_logging

logger, log_buffer = setup_service_logging("hestia_archive")

# ── Database bootstrap ────────────────────────────────────────────────────────
def _bootstrap_database() -> None:
    """Wait for Postgres (boot ordering), then ensure pgvector + tables.
    ARCHIVE_DB_WAIT_SECONDS=0 waits forever (Startup Readiness Contract)."""
    import time as _time
    limit = float(os.getenv("ARCHIVE_DB_WAIT_SECONDS", "0"))
    started = _time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        try:
            schema.migrate(engine)
            return
        except Exception as exc:
            if limit and _time.monotonic() - started > limit:
                raise
            logger.warning("[🔄] event=archive_db_not_ready attempt=%d error=%s", attempt, str(exc)[:200])
            _time.sleep(min(30, 2 * attempt))


_bootstrap_database()

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
app.include_router(settings.router)
app.include_router(presence.router)
app.include_router(chat_queue.router)
app.include_router(hercules_store.router)
app.include_router(selfcare_store.router)
app.include_router(wardrobe_store.router)
app.include_router(blobs.router)
app.include_router(mcp_access_store.router)
app.include_router(module_store.finance_router)   # Plutus (expenses)
app.include_router(module_store.iris_router)      # Iris (mail subscriptions)
app.include_router(module_store.echo_router)      # Echo (kept audio index, voice usage)
app.include_router(module_store.oracle_router)    # Oracle (pending questions to the user)
app.include_router(module_store.argus_router)     # Argus (notable events journal)
app.include_router(module_store.hermes_router)    # Hermes (Web Push subscriptions)
app.include_router(module_store.chronos_router)   # Chronos (routine results, smart-calendar choices)
app.include_router(module_store.athena_router)    # Athena (learning log, memory review proposals)
app.include_router(module_store.apollo_router)    # Apollo (images-store)
app.include_router(module_store.aphrodite_router) # Aphrodite (appearance-store)
app.include_router(module_store.lares_router)     # Lares (home-store)
app.include_router(module_store.hera_router)      # Hera (people-store)
app.include_router(module_store.demeter_router)   # Demeter (food-store)
app.include_router(module_store.calliope_router)  # Calliope (office-store)
app.include_router(module_store.kairos_router)    # Kairos (deadlines-store)
app.include_router(module_store.psyche_router)    # Psyche (mood-store)
app.include_router(module_store.metis_router)     # Metis (metis-store usage log)
app.include_router(module_store.dataset_router)   # Metis (dataset-store: chat turn traces for training)
app.include_router(module_store.signals_router)   # reflection signals (modules → Athena)

# Backup to Google Drive, verification, rollback (docs/work/2026-10-20-backup-drive) + maintenance gate.
from .backup import wiring as backup_wiring  # noqa: E402
backup_service = backup_wiring.setup(app, engine, database.SQLALCHEMY_DATABASE_URL)

# ── MCP tools ──────────────────────────────────────────────────────────────────
try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    def _feedback_submit_handler(
        session_id: str = "",
        interaction_id: str = "",
        quality_label: str = "mixed",
        quality_score: int = None,
        feedback_text: str = "",
        tags: list = None,
    ) -> dict:
        """Persist a quality feedback record via Archive's own DB session."""
        import uuid

        db = SessionLocal()
        try:
            feedback_id = f"fbk-{uuid.uuid4().hex[:16]}"
            row = models.FeedbackRecord(
                feedback_id=feedback_id,
                session_id=str(session_id or "").strip() or None,
                interaction_id=str(interaction_id or "").strip() or None,
                source_service="mcp",
                quality_label=str(quality_label or "mixed").strip().lower(),
                quality_score=int(quality_score) if quality_score is not None else None,
                feedback_text=str(feedback_text or "").strip() or None,
                tags=list(tags or []) if isinstance(tags, list) else [],
                payload={},
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return {
                "status": "stored",
                "feedback_id": row.feedback_id,
                "quality_label": row.quality_label,
            }
        except Exception as exc:
            db.rollback()
            return {"status": "error", "error": str(exc)}
        finally:
            db.close()

    _archive_mcp_tools = [
        MCPTool(
            name="feedback_submit",
            description=(
                "Store a quality grade for a chat interaction. "
                "Pure persistence — no business logic. "
                "Used by clients (Telegram, web UI) after rendering an assistant response."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session identifier for the conversation",
                    },
                    "interaction_id": {
                        "type": "string",
                        "description": "Specific interaction/message identifier",
                    },
                    "quality_label": {
                        "type": "string",
                        "enum": ["excellent", "good", "mixed", "poor", "rejected"],
                        "description": "Quality grade label",
                    },
                    "quality_score": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Optional numeric quality score 1-5",
                    },
                    "feedback_text": {
                        "type": "string",
                        "description": "Optional free-text feedback",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization",
                    },
                },
                "required": ["session_id", "quality_label"],
            },
            handler=_feedback_submit_handler,
            title="Rate answer",
            method="POST",
            path="/api/feedback",
            clients=["telegram", "ui"],
            response_mode="direct",
            telegram_visible=False, telegram_group="system",
                telegram={"section": "interno"}),
        # Backup from every client (dossier docs/work/2026-10-24-tutto-brainstorm-cindy F). Restore is NOT a tool:
        # only the owner restores (Telegram «Ripristina un backup», WebUI Backup panel), never the assistant.
        MCPTool(
            name="backup_status",
            description="Backup state: last backup, last check, problems, Google Drive linked.",
            parameters={"type": "object", "properties": {}},
            handler=lambda **_kw: {"status": "ok"}, title="Backup status", method="GET",
            path="/api/backup/status", clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Two or three lines: last backup (when, result), last check, any problem.",
            telegram_visible=True, telegram_group="system",
                telegram={"section": "Data and backups", "label": "Backup"}),
        MCPTool(
            name="backup_list",
            description="List of the backups on Google Drive (date, size).",
            parameters={"type": "object", "properties": {}},
            handler=lambda **_kw: {"status": "ok"}, title="Saved backups", method="GET",
            path="/api/backup/list", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="system",
                telegram={"section": "Data and backups"}),
        MCPTool(
            name="backup_run",
            description="Make an encrypted backup of all data on Google Drive now (takes a few minutes).",
            parameters={"type": "object", "properties": {}},
            handler=lambda **_kw: {"status": "ok"}, title="Back up now", method="POST",
            path="/api/backup/run", clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="system",
                telegram={"section": "Data and backups", "label": "Back up now"}),
    ]
    app.include_router(
        create_mcp_router(_archive_mcp_tools, service_name="archive")
    )
    logger.info("event=mcp_router_mounted service=archive tools=%d", len(_archive_mcp_tools))
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=archive reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_archive"))

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
                "command": "preferences_active",
                "title": "Active preferences",
                "telegram_group": "memory",
                "telegram": {"section": "Notes and preferences"},
                "description": "Show the user's active preferences",
                "method": "GET",
                "path": "/api/memory/active",
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "List the active preferences briefly, grouped by domain, in natural language.",
            },
            {
                "command": "notifications_active",
                "title": "Automatic alerts",
                "telegram_group": "notifications",
                "telegram": {"section": "Automatic alerts", "label": "Automatic alerts"},
                "description": "Show the active automatic notifications",
                "method": "GET",
                "path": "/api/subscriptions/active",
                "clients": ["telegram", "ui"],
                "response_mode": "raw_json",
            },
            {
                "command": "alerts_recent",
                "title": "Recent notices",
                "telegram_group": "notifications",
                "telegram": {"section": "Automatic alerts"},
                "description": "Show the latest notices sent",
                "method": "GET",
                "path": "/api/dispatch/logs/enriched",
                "query_template": {"limit": 15, "hours": 72},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Recent notices timeline: for each the item's full title, key payload details, 24h date/time, delivered yes/no. Link on the title, never 'Open'. Concise.",
            },
            {
                "command": "notification_disable",
                "title": "Turn off a notice",
                "telegram_group": "notifications",
                "telegram": {"section": "Automatic alerts"},
                "description": "Turn off a notification by subscription_id",
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
                "response_prompt": "Confirm clearly that the notification is off.",
            },
            {
                "command": "notification_enable",
                "title": "Turn a notice back on",
                "telegram_group": "notifications",
                "telegram": {"section": "Automatic alerts"},
                "description": "Turn a notification back on by subscription_id",
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
                "response_prompt": "Confirm clearly that the notification is on again.",
            },
            # ── Calendar reminder subscriptions ───────────────────────────────
            {
                "command": "calendar_subscribe",
                "title": "Turn on calendar reminders",
                "telegram_group": "notifications",
                "telegram": {"section": "Reminders and alerts"},
                "description": "Get automatic reminders for calendar events",
                "method": "POST",
                "path": "/api/subscriptions",
                "body_template": {
                    "subscription_id": "cal-reminder-$chat_id",
                    "owner": "$chat_id",
                    "domain": "calendar",
                    "event_type": "calendar.reminder",
                    "filters": {},
                    "channels": [{"type": "all", "target": "owner"}],
                    "is_active": True,
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Confirm briefly that calendar reminders are on.",
            },
            {
                "command": "calendar_unsubscribe",
                "title": "Turn off calendar reminders",
                "telegram_group": "notifications",
                "telegram": {"section": "Reminders and alerts"},
                "description": "Stop automatic calendar reminders",
                "method": "PATCH",
                "path": "/api/subscriptions/cal-reminder-$chat_id/active",
                "body_template": {"is_active": False},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Confirm briefly that calendar reminders are off.",
            },
            # ── System health alert subscriptions ─────────────────────────────
            {
                "command": "system_subscribe",
                "title": "Turn on system alerts",
                "telegram_group": "notifications",
                "telegram": {"section": "Reminders and alerts"},
                "description": "Get notifications about the services' status",
                "method": "POST",
                "path": "/api/subscriptions",
                "body_template": {
                    "subscription_id": "sys-health-$chat_id",
                    "owner": "$chat_id",
                    "domain": "system",
                    "event_type": "service.health",
                    "filters": {},
                    "channels": [{"type": "all", "target": "owner"}],
                    "is_active": True,
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Confirm briefly that system alerts are on.",
            },
            {
                "command": "system_unsubscribe",
                "title": "Turn off system alerts",
                "telegram_group": "notifications",
                "telegram": {"section": "Reminders and alerts"},
                "description": "Stop notifications about the services' status",
                "method": "PATCH",
                "path": "/api/subscriptions/sys-health-$chat_id/active",
                "body_template": {"is_active": False},
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Confirm briefly that system alerts are off.",
            },
            {
                "command": "archive_reconcile",
                "title": "Reconcile archive",
                "telegram_group": "system",
                "telegram": {"section": "Advanced"},
                "description": "Run a reconciliation maintenance on Archive entity records",
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
                        "description": "If true only simulates, no deletions",
                    },
                    "domain": {
                        "type": "string",
                        "required": False,
                        "description": "Optional domain to limit the reconciliation to",
                    },
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
                "response_prompt": "Summarise the reconciliation result: records analysed, changes applied and whether it was a dry run.",
            },
        ],
    },
}


@app.on_event("startup")
def register_on_hub_startup():
    """Register on Hub now and keep re-registering (Hub restarts lose the registry)."""
    _register_on_hub()
    backup_wiring.start()
    try:
        from hestia_common.startup_utils import start_hub_keepalive
        start_hub_keepalive(_register_on_hub, logger=logger)
    except ImportError:
        logger.warning("[🔄] event=hub_keepalive_unavailable reason=hestia_common_missing")


def _register_on_hub():
    """Register this service with the Hub (best-effort)."""
    hub_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    payload = {**_HUB_REGISTRATION_PAYLOAD, "capabilities": {
        **_HUB_REGISTRATION_PAYLOAD["capabilities"],
        **backup_wiring.capabilities(_HUB_REGISTRATION_PAYLOAD["base_url"])}}   # Backup panel (plugin)
    try:
        resp = requests.post(f"{hub_url}/registry/register",
                             json=payload, timeout=4)
        if resp.status_code < 400:
            log_event(
                logger,
                logging.DEBUG,
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

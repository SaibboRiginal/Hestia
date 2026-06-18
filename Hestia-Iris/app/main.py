from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from uuid import uuid4

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready

logger, log_buffer = setup_service_logging("hestia_iris")

app = FastAPI(title="Hestia-Iris", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────────────────────────────
#  MCP tools
# ─────────────────────────────────────────────────────────────────────

try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    _iris_mcp_tools = [
        MCPTool(
            name="email_search",
            description="Cerca messaggi email per testo",
            parameters={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Testo da cercare"},
                    "limit": {"type": "integer", "description": "Numero massimo risultati (max 200)"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "email_search", "params": kw},
            title="\U0001f4e8 Cerca messaggi", method="GET", path="/api/email/messages",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="notifiche",
        ),
        MCPTool(
            name="email_send",
            description="Invia una email",
            parameters={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Destinatario"},
                    "subject": {"type": "string", "description": "Oggetto"},
                    "body": {"type": "string", "description": "Corpo del messaggio"},
                    "thread_id": {"type": "string", "description": "ID thread per rispondere in un thread esistente"},
                },
                "required": ["to", "subject", "body"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "email_send", "params": kw},
            title="\U0001f4e4 Invia messaggio", method="POST", path="/api/email/send",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="notifiche",
        ),
        MCPTool(
            name="email_thread",
            description="Mostra un thread email",
            parameters={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "ID del thread"},
                },
                "required": ["id"],
            },
            handler=lambda **kw: {"status": "ok", "tool": "email_thread", "params": kw},
            title="\U0001f4ac Vedi conversazione", method="GET", path="/api/email/threads/$arg.id",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            telegram_visible=True, telegram_group="notifiche",
        ),
        MCPTool(
            name="iris_reconcile",
            description="Esegue manutenzione di riconciliazione nel modulo Iris",
            parameters={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "Se true esegue solo simulazione senza modifiche"},
                },
            },
            handler=lambda **kw: {"status": "ok", "tool": "iris_reconcile", "params": kw},
            title="\U0001f6e0️ Riconcilia email", method="POST", path="/api/module/maintenance/reconcile",
            clients=["telegram", "ui"], response_mode="oracle_natural",
            response_prompt="Riassumi l'esito della riconciliazione Iris, indicando lo stato del modulo email.",
            telegram_visible=True, telegram_group="altro",
        ),
    ]
    app.include_router(create_mcp_router(_iris_mcp_tools, service_name="iris"))
    logger.info("event=mcp_router_mounted service=iris")
except ModuleNotFoundError:
    logger.info("event=mcp_router_skipped service=iris reason=hestia_common_not_available")

app.include_router(create_log_control_router("hestia_iris"))

_MESSAGES: list[dict[str, Any]] = []


class EmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    thread_id: str | None = None


class ModuleMaintenanceRequest(BaseModel):
    source: str = "oracle"
    task_id: str | None = None
    issue: str | None = None
    requested_action: str | None = "reconcile_email"
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def register_on_hub_startup() -> None:
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "IRIS_SERVICE_BASE_URL", "http://hestia_iris:19012")
    startup_wait_timeout = float(
        os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))

    payload = {
        "name": "iris",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "module",
        "service_version": os.getenv("IRIS_SERVICE_VERSION", "1.0.0"),
        "tags": ["module", "integration"],
        "topology_tags": ["layer:domain", "domain:email", "status:experimental"],
        "capabilities": {
            "mcp_endpoint": f"{service_base_url.rstrip('/')}/mcp",
            "module_tool_domains": ["email"],
        },
    }

    wait_for_http_ready(
        hub_health_url(hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )

    def _register_once() -> None:
        response = requests.post(
            f"{hub_api_url}/registry/register", json=payload, timeout=4)
        response.raise_for_status()

    try:
        _register_once()
        logger.info(
            "event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s", "iris", service_base_url)
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", error)

    def _hub_keepalive() -> None:
        while True:
            time.sleep(60)
            try:
                _register_once()
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s", error)

    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hestia_iris"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None) -> dict[str, Any]:
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_iris",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/email/inbox")
def email_inbox(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    messages = sorted(
        _MESSAGES, key=lambda row: row["created_at"], reverse=True)[:limit]
    return {"status": "ok", "count": len(messages), "messages": messages}


@app.get("/api/email/messages")
def email_messages(q: str = "", limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    t0 = time.perf_counter()
    needle = q.strip().lower()
    rows = _MESSAGES
    if needle:
        rows = [
            row
            for row in _MESSAGES
            if needle in row.get("subject", "").lower()
            or needle in row.get("body", "").lower()
            or needle in row.get("to", "").lower()
        ]
    rows = sorted(rows, key=lambda row: row["created_at"], reverse=True)[
        :limit]
    logger.info(
        "event=email_search_done ms=%d query_len=%d results=%d",
        int((time.perf_counter() - t0) * 1000),
        len(q),
        len(rows),
    )
    return {"status": "ok", "query": q, "count": len(rows), "messages": rows}


@app.post("/api/email/send")
def email_send(req: EmailSendRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    message_id = f"iris-{int(time.time() * 1000)}"
    thread_id = req.thread_id or message_id
    row = {
        "id": message_id,
        "thread_id": thread_id,
        "to": req.to,
        "subject": req.subject,
        "body": req.body,
        "created_at": _now_iso(),
        "direction": "outbound",
    }
    _MESSAGES.append(row)
    logger.info(
        "event=email_send_done ms=%d thread_id=%s",
        int((time.perf_counter() - t0) * 1000),
        thread_id,
    )
    return {"status": "ok", "sent": row}


@app.get("/api/email/threads/{thread_id}")
def email_thread(thread_id: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    rows = [row for row in _MESSAGES if row.get("thread_id") == thread_id]
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"thread '{thread_id}' not found")
    rows = sorted(rows, key=lambda row: row["created_at"])
    logger.info(
        "event=email_thread_done ms=%d thread_id=%s message_count=%d",
        int((time.perf_counter() - t0) * 1000),
        thread_id,
        len(rows),
    )
    return {"status": "ok", "thread_id": thread_id, "count": len(rows), "messages": rows}


@app.post("/api/module/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def module_maintenance_reconcile(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    task_id = str(req.task_id or uuid4())
    action = str(req.requested_action or "reconcile_email").strip().lower()

    message_count = len(_MESSAGES)

    if req.dry_run:
        return ModuleMaintenanceResponse(
            status="ok",
            service="iris",
            dry_run=True,
            task_id=task_id,
            executed_at=datetime.now(timezone.utc),
            retriable=True,
            summary="Iris maintenance dry-run accepted: no state mutations executed.",
            mutation_count=0,
            details={
                "requested_action": action,
                "in_memory_message_count": message_count,
                "note": "Set dry_run=false to execute reconcile pass.",
            },
        )

    return ModuleMaintenanceResponse(
        status="ok",
        service="iris",
        dry_run=False,
        task_id=task_id,
        executed_at=datetime.now(timezone.utc),
        retriable=True,
        summary="Iris maintenance reconcile executed: in-memory state validated.",
        mutation_count=0,
        details={
            "requested_action": action,
            "in_memory_message_count": message_count,
        },
    )


@app.post("/api/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def maintenance_reconcile_alias(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    return module_maintenance_reconcile(req)

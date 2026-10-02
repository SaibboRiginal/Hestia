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

def _hecate(method: str, path: str, *, query: dict | None = None, body: dict | None = None,
            timeout: float = 30) -> dict[str, Any]:
    """Provider mail lives in Hecate (single provider gateway): call it via Hub.
    (Iris used to keep an in-memory list: nothing was ever read or sent.)"""
    hub = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    try:
        resp = requests.post(
            f"{hub}/route/hecate/{path.lstrip('/')}",
            json={"method": method, "headers": {}, "query": query or {}, "body": body,
                  "timeout_seconds": timeout},
            timeout=timeout + 5)
        resp.raise_for_status()
        routed = resp.json() or {}
    except Exception as exc:
        logger.warning("[🔄] event=iris_hecate_unreachable path=%s error=%s", path, exc)
        raise HTTPException(status_code=503, detail=f"Hecate unreachable: {exc}")
    status = int(routed.get("status_code", 500))
    payload = routed.get("payload") or {}
    if status >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise HTTPException(status_code=status, detail=detail or "mail provider error")
    return payload if isinstance(payload, dict) else {}


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


HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def register_on_hub_startup() -> None:
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
        hub_health_url(HUB_API_URL),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )

    def _register_once() -> None:
        response = requests.post(
            f"{HUB_API_URL}/registry/register", json=payload, timeout=4)
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
    data = _hecate("GET", "api/gateway/email/messages", query={"limit": limit})
    messages = data.get("messages") or []
    return {"status": "ok", "count": len(messages), "messages": messages}


@app.get("/api/email/messages")
def email_messages(q: str = "", since: str | None = None,
                   limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    """Search mail. ``q`` = free text or raw IMAP criteria ('FROM "x"'); ``since`` = ISO date."""
    t0 = time.perf_counter()
    query: dict[str, Any] = {"q": q, "limit": limit}
    if since:
        query["since"] = since
    try:
        data = _hecate("GET", "api/gateway/email/messages", query=query)
    except HTTPException as exc:
        # Soft error: chat/tools get a readable reason instead of a 5xx.
        logger.warning("[🔄] event=hecate_email_gateway_failed status=%s detail=%s",
                       exc.status_code, str(exc.detail)[:300])
        return {"status": "error", "query": q, "count": 0, "messages": [],
                "error": f"Hecate: {str(exc.detail)[:300]}"}
    rows = data.get("messages") or []
    logger.info(
        "event=email_search_done ms=%d query_len=%d results=%d backend=%s",
        int((time.perf_counter() - t0) * 1000), len(q), len(rows), data.get("backend"),
    )
    if data.get("status") == "error":
        return {"status": "error", "query": q, "count": 0, "messages": [],
                "error": data.get("error"), "action_required": data.get("action_required")}
    return {"status": "ok", "query": q, "backend": data.get("backend"), "count": len(rows), "messages": rows}


@app.post("/api/email/ingest")
def email_ingest(body: dict[str, Any]) -> dict[str, Any]:
    """Trigger a provider mail fetch through Hecate (``/api/ingest/trigger``).
    Domain modules (Scout) call Iris — Iris owns the email domain."""
    try:
        return _hecate("POST", "api/ingest/trigger", body=body, timeout=120) or {"status": "ok"}
    except HTTPException as exc:
        logger.warning("[🔄] event=iris_ingest_failed status=%s detail=%s", exc.status_code, exc.detail)
        return {"status": "error", "detail": str(exc.detail)[:300]}


@app.post("/api/email/send")
def email_send(req: EmailSendRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    subject = req.subject
    if req.thread_id and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    sent = _hecate("POST", "api/gateway/email/send",
                   body={"to": req.to, "subject": subject, "body": req.body}).get("sent") or {}
    sent["thread_id"] = req.thread_id or subject.lower()
    logger.info("event=email_send_done ms=%d", int((time.perf_counter() - t0) * 1000))
    return {"status": "ok", "sent": sent}


@app.get("/api/email/threads/{thread_id}")
def email_thread(thread_id: str) -> dict[str, Any]:
    """Thread = messages sharing the normalized subject (provider-agnostic)."""
    rows = _hecate("GET", "api/gateway/email/messages",
                   query={"q": f'SUBJECT "{thread_id}"', "limit": 100}).get("messages") or []
    rows = [r for r in rows if r.get("thread_id") == thread_id] or rows
    if not rows:
        raise HTTPException(status_code=404, detail=f"thread '{thread_id}' not found")
    rows = sorted(rows, key=lambda row: row.get("created_at") or "")
    return {"status": "ok", "thread_id": thread_id, "count": len(rows), "messages": rows}


@app.post("/api/module/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def module_maintenance_reconcile(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    task_id = str(req.task_id or uuid4())
    action = str(req.requested_action or "reconcile_email").strip().lower()

    try:
        provider = _hecate("GET", "api/gateway/mail/status", timeout=10)
    except HTTPException as exc:
        provider = {"configured": False, "error": str(exc.detail)}

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
                "mail_provider": provider,
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
        summary="Iris maintenance reconcile executed: mail provider checked via Hecate.",
        mutation_count=0,
        details={
            "requested_action": action,
            "mail_provider": provider,
        },
    )


@app.post("/api/maintenance/reconcile", response_model=ModuleMaintenanceResponse)
def maintenance_reconcile_alias(req: ModuleMaintenanceRequest) -> ModuleMaintenanceResponse:
    return module_maintenance_reconcile(req)

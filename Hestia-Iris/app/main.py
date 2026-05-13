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

try:
    from hestia_common.logging_utils import setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready

logger, log_buffer = setup_service_logging("hestia_iris")

app = FastAPI(title="Hestia-Iris", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])

_MESSAGES: list[dict[str, Any]] = []


class EmailSendRequest(BaseModel):
    to: str
    subject: str
    body: str
    thread_id: str | None = None


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
            "commands": [
                {
                    "command": "email_search",
                    "title": "Email - Cerca messaggi",
                    "description": "Cerca messaggi email per testo",
                    "method": "GET",
                    "path": "/api/email/messages",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                },
                {
                    "command": "email_send",
                    "title": "Email - Invia",
                    "description": "Invia una email",
                    "method": "POST",
                    "path": "/api/email/send",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                },
                {
                    "command": "email_thread",
                    "title": "Email - Thread",
                    "description": "Mostra un thread email",
                    "method": "GET",
                    "path": "/api/email/threads/$arg.id",
                    "arguments_help": "id=<thread_id>",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                },
            ]
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
    return {"status": "ok", "query": q, "count": len(rows), "messages": rows}


@app.post("/api/email/send")
def email_send(req: EmailSendRequest) -> dict[str, Any]:
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
    return {"status": "ok", "sent": row}


@app.get("/api/email/threads/{thread_id}")
def email_thread(thread_id: str) -> dict[str, Any]:
    rows = [row for row in _MESSAGES if row.get("thread_id") == thread_id]
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"thread '{thread_id}' not found")
    rows = sorted(rows, key=lambda row: row["created_at"])
    return {"status": "ok", "thread_id": thread_id, "count": len(rows), "messages": rows}

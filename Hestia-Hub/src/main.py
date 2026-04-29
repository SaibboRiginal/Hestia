"""Hestia Hub — FastAPI application entry-point.

Single responsibility: wire the HTTP layer (routes, lifespan) to the service
modules.  All business logic lives in the ``modules/`` package.
"""
import logging
import os
from pathlib import Path
import sys

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

try:
    from hestia_common.logging_utils import (
        log_event,
        redact_sensitive_text,
        setup_service_logging,
    )
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import (
        log_event,
        redact_sensitive_text,
        setup_service_logging,
    )

from .modules.discovery import discover_commands, discover_module_tools
from .modules.events import RegistryEvents
from .modules.registry import ServiceRegistry
from .modules.router import proxy_request
from .modules.schemas import (
    ALLOWED_TAGS,
    DeregisterServiceRequest,
    RegisterServiceRequest,
    RouteRequest,
)

logger, log_buffer = setup_service_logging("hestia_hub")

# ── Singletons ────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia Hub", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
registry = ServiceRegistry()
events = RegistryEvents(
    notify_timeout=float(os.getenv("HUB_NOTIFY_TIMEOUT", "2")),
)
_health_timeout = float(os.getenv("HUB_HEALTHCHECK_TIMEOUT", "3"))

# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hub"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_hub",
        "count": len(rows),
        "logs": rows,
    }

# ── Registry ──────────────────────────────────────────────────────────────────


@app.post("/api/registry/register")
def register_service(req: RegisterServiceRequest):
    service = req.model_dump()
    register_status = registry.register(service)
    if register_status != "refreshed":
        events.bump(registry.all_services(), reason="register")
    log_event(
        logger,
        logging.DEBUG if register_status == "refreshed" else logging.INFO,
        "service_registered",
        service="hub",
        register_status=register_status,
        name=req.name,
        base_url=redact_sensitive_text(req.base_url),
    )
    return {"status": "ok"}


@app.post("/api/registry/deregister")
def deregister_service(req: DeregisterServiceRequest):
    registry.deregister(req.name, req.base_url)
    events.bump(registry.all_services(), reason="deregister")
    log_event(
        logger,
        logging.INFO,
        "service_deregistered",
        service="hub",
        name=req.name,
        base_url=redact_sensitive_text(req.base_url),
    )
    return {"status": "ok"}


@app.get("/api/registry/revision")
def get_registry_revision():
    return {
        "revision": events.revision,
        "updated_at": events.updated_at,
        "services_count": len(registry.all_services()),
    }


@app.get("/api/registry/wait")
def wait_registry_revision(after_revision: int = 0, timeout_seconds: float = 120.0):
    revision, updated_at, changed = events.wait_for_change(
        after_revision=after_revision,
        timeout_seconds=min(300.0, max(1.0, timeout_seconds)),
    )
    return {
        "revision": revision,
        "updated_at": updated_at,
        "changed": changed,
        "services_count": len(registry.all_services()),
    }


@app.get("/api/registry/services")
def list_services():
    return {"services": registry.all_services()}

# ── Discovery ─────────────────────────────────────────────────────────────────


@app.get("/api/discovery/module-tools")
def module_tools_discovery():
    return {"mapping": discover_module_tools(registry)}


@app.get("/api/discovery/commands")
def discovery_commands_endpoint(client: str | None = None):
    commands = discover_commands(registry, client_key=client or "")
    return {"commands": commands}

# ── Standards ─────────────────────────────────────────────────────────────────


@app.get("/api/standards/registration")
def registration_standard():
    return {
        "service_type_allowed": ["core", "module", "integration"],
        "tags_allowed": sorted(ALLOWED_TAGS),
        "service_version_format": "major.minor.patch",
        "rules": [
            "service name: lowercase [a-z0-9_-]{2,40}",
            "base_url: must start with http:// or https://",
            "health_endpoint: must start with /",
            "capabilities keys: snake_case [a-z0-9_]",
            "tags must include service_type",
            "optional capabilities.commands entries can expose direct user commands",
        ],
        "example": {
            "name": "example_service",
            "base_url": "http://example_service:8080",
            "health_endpoint": "/health",
            "service_type": "integration",
            "service_version": "1.0.0",
            "tags": ["integration", "messaging"],
            "capabilities": {
                "health_check": "/health",
                "commands": [
                    {
                        "command": "status",
                        "description": "Service quick status",
                        "method": "GET",
                        "path": "/health",
                        "clients": ["telegram", "ui"],
                        "response_mode": "text",
                    }
                ],
            },
        },
    }

# ── Routing ───────────────────────────────────────────────────────────────────


@app.post("/api/route/{service_name}/{path:path}")
def route_request(service_name: str, path: str, req: RouteRequest):
    candidates = registry.get(service_name)
    if not candidates:
        raise HTTPException(
            status_code=404, detail=f"Service not registered: {service_name}")

    last_error = None
    for service in candidates:
        try:
            status_code, payload = proxy_request(
                base_url=service["base_url"],
                path=path,
                method=req.method,
                query=req.query,
                body=req.body,
                headers=req.headers,
                timeout_seconds=req.timeout_seconds,
            )
            return {
                "status_code": status_code,
                "service": service_name,
                "target": service["base_url"],
                "payload": payload,
            }
        except requests.RequestException as error:
            last_error = error
            continue

    raise HTTPException(
        status_code=503,
        detail={
            "service": service_name,
            "message": "No available instance responded",
            "error": str(last_error) if last_error else "unknown",
        },
    )


@app.get("/api/monitor/logs/{service_name}")
def monitor_logs(
    service_name: str,
    limit: int = 200,
    level: str | None = None,
    contains: str | None = None,
    mode: str = "raw",
    response_prompt: str | None = None,
    include_raw: bool = False,
    timeout_seconds: float = 8.0,
):
    candidates = registry.get(service_name)
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"Service not registered: {service_name}",
        )

    query: dict[str, object] = {"limit": max(1, min(limit, 2000))}
    if level:
        query["level"] = level
    if contains:
        query["contains"] = contains

    last_error = None
    for service in candidates:
        try:
            status_code, payload = proxy_request(
                base_url=service["base_url"],
                path="api/logs",
                method="GET",
                query=query,
                body=None,
                headers={},
                timeout_seconds=timeout_seconds,
            )
            if status_code < 400:
                raw_response = {
                    "status_code": status_code,
                    "service": service_name,
                    "target": redact_sensitive_text(str(service["base_url"])),
                    "payload": payload,
                }

                mode_normalized = (mode or "raw").strip().lower()
                if mode_normalized == "raw":
                    return raw_response

                rows = []
                if isinstance(payload, dict):
                    rows = payload.get("logs") or []
                if not isinstance(rows, list):
                    rows = []

                lines = [
                    str(row.get("formatted") or row.get("message") or "")
                    for row in rows
                    if isinstance(row, dict)
                ]
                text = "\n".join(line for line in lines if line)

                if mode_normalized in {"text", "transcribe"}:
                    return {
                        "status_code": status_code,
                        "service": service_name,
                        "target": redact_sensitive_text(str(service["base_url"])),
                        "mode": "text",
                        "text": text,
                        "line_count": len(lines),
                        **({"payload": payload} if include_raw else {}),
                    }

                if mode_normalized in {"ai", "analyze", "summary"}:
                    oracle_candidates = registry.get("oracle")
                    if oracle_candidates:
                        oracle_base = str(
                            oracle_candidates[0].get("base_url", "")
                        ).rstrip("/")
                        if oracle_base:
                            try:
                                oracle_response = requests.post(
                                    f"{oracle_base}/api/format",
                                    json={
                                        "command": "monitor.logs",
                                        "payload": {
                                            "service": service_name,
                                            "line_count": len(lines),
                                            "logs": rows,
                                        },
                                        "response_prompt": response_prompt
                                        or "Analyze these service logs and summarize key issues, warnings, and actions.",
                                        "max_length": 1800,
                                    },
                                    timeout=max(2.0, timeout_seconds),
                                )
                                if oracle_response.status_code < 400:
                                    ai_text = str(
                                        (oracle_response.json()
                                         or {}).get("text", "")
                                    ).strip()
                                    if ai_text:
                                        return {
                                            "status_code": status_code,
                                            "service": service_name,
                                            "target": redact_sensitive_text(str(service["base_url"])),
                                            "mode": "ai",
                                            "text": ai_text,
                                            "line_count": len(lines),
                                            **({"payload": payload} if include_raw else {}),
                                        }
                            except requests.RequestException:
                                pass

                    return {
                        "status_code": status_code,
                        "service": service_name,
                        "target": redact_sensitive_text(str(service["base_url"])),
                        "mode": "text_fallback",
                        "text": text,
                        "line_count": len(lines),
                        **({"payload": payload} if include_raw else {}),
                    }

                return {
                    "status_code": 400,
                    "service": service_name,
                    "detail": "Unsupported mode. Use raw | text | transcribe | ai | analyze | summary",
                }
            last_error = f"status={status_code}"
        except requests.RequestException as error:
            last_error = str(error)
            continue

    raise HTTPException(
        status_code=503,
        detail={
            "service": service_name,
            "message": "No available instance returned logs",
            "error": redact_sensitive_text(last_error or "unknown"),
        },
    )

# ── Status ────────────────────────────────────────────────────────────────────


@app.get("/api/status")
def status():
    services = []
    for service in registry.all_services():
        endpoint = f"{service['base_url'].rstrip('/')}{service.get('health_endpoint', '/health')}"
        item = dict(service)
        try:
            response = requests.get(endpoint, timeout=_health_timeout)
            item["health"] = "healthy" if response.status_code < 400 else "degraded"
            item["health_status_code"] = response.status_code
        except requests.RequestException:
            item["health"] = "unavailable"
            item["health_status_code"] = None
        services.append(item)

    return {"services": services}

"""Hestia Hub — FastAPI application entry-point.

Single responsibility: wire the HTTP layer (routes, lifespan) to the service
modules.  All business logic lives in the ``modules/`` package.
"""
import logging
import os

import requests
from fastapi import FastAPI, HTTPException

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("hestia_hub")

# ── Singletons ────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia Hub", version="1.0.0")
registry = ServiceRegistry()
events = RegistryEvents(
    notify_timeout=float(os.getenv("HUB_NOTIFY_TIMEOUT", "2")),
)
_health_timeout = float(os.getenv("HUB_HEALTHCHECK_TIMEOUT", "3"))

# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hub"}

# ── Registry ──────────────────────────────────────────────────────────────────


@app.post("/api/registry/register")
def register_service(req: RegisterServiceRequest):
    service = req.model_dump()
    registry.register(service)
    events.bump(registry.all_services(), reason="register")
    logger.info("Service registered | name=%s base_url=%s", req.name, req.base_url)
    return {"status": "ok"}


@app.post("/api/registry/deregister")
def deregister_service(req: DeregisterServiceRequest):
    registry.deregister(req.name, req.base_url)
    events.bump(registry.all_services(), reason="deregister")
    logger.info("Service deregistered | name=%s base_url=%s", req.name, req.base_url)
    return {"status": "ok"}


@app.get("/api/registry/revision")
def get_registry_revision():
    return {
        "revision": events.revision,
        "updated_at": events.updated_at,
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
        raise HTTPException(status_code=404, detail=f"Service not registered: {service_name}")

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

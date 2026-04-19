import logging
import os
import re
import threading
import time

import requests
from fastapi import FastAPI, HTTPException

from .modules.discovery import discover_module_tools
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
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("hestia_hub")

app = FastAPI(title="Hestia Hub", version="1.0.0")
registry = ServiceRegistry()
health_timeout = float(os.getenv("HUB_HEALTHCHECK_TIMEOUT", "3"))
notify_timeout = float(os.getenv("HUB_NOTIFY_TIMEOUT", "2"))
registry_revision = 0
registry_updated_at = time.time()


def _notify_registry_change(reason: str):
    payload = {
        "event": "hub.registry.changed",
        "reason": reason,
        "revision": registry_revision,
        "updated_at": registry_updated_at,
    }

    for service in registry.all_services():
        capabilities = service.get("capabilities") or {}
        webhook_path = str(capabilities.get("hub_events_webhook", "")).strip()
        if not webhook_path.startswith("/"):
            continue

        endpoint = f"{str(service.get('base_url', '')).rstrip('/')}{webhook_path}"
        try:
            requests.post(endpoint, json=payload, timeout=notify_timeout)
        except requests.RequestException:
            logger.debug("Registry notify failed | endpoint=%s", endpoint)


def _bump_registry_revision(reason: str):
    global registry_revision, registry_updated_at
    registry_revision += 1
    registry_updated_at = time.time()
    notify_thread = threading.Thread(
        target=_notify_registry_change, args=(reason,), daemon=True)
    notify_thread.start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hub"}


@app.post("/api/registry/register")
def register_service(req: RegisterServiceRequest):
    service = req.model_dump()
    registry.register(service)
    _bump_registry_revision(reason="register")
    logger.info("Service registered | name=%s base_url=%s",
                req.name, req.base_url)
    return {"status": "ok"}


@app.post("/api/registry/deregister")
def deregister_service(req: DeregisterServiceRequest):
    registry.deregister(req.name, req.base_url)
    _bump_registry_revision(reason="deregister")
    logger.info("Service deregistered | name=%s base_url=%s",
                req.name, req.base_url)
    return {"status": "ok"}


@app.get("/api/registry/revision")
def get_registry_revision():
    return {
        "revision": registry_revision,
        "updated_at": registry_updated_at,
        "services_count": len(registry.all_services()),
    }


@app.get("/api/registry/services")
def list_services():
    services = registry.all_services()
    return {"services": services}


@app.get("/api/discovery/module-tools")
def module_tools_discovery():
    return {"mapping": discover_module_tools(registry)}


@app.get("/api/discovery/commands")
def discover_commands(client: str | None = None):
    discovered_map: dict[tuple[str, str], dict] = {}
    client_key = str(client or "").strip().lower()

    for service in registry.all_services():
        capabilities = service.get("capabilities") or {}
        commands = capabilities.get("commands") or []
        if not isinstance(commands, list):
            continue

        for command in commands:
            if not isinstance(command, dict):
                continue

            name = str(command.get("command", "")).strip().lower()
            if not re.fullmatch(r"[a-z0-9_]{2,32}", name):
                continue

            service_name = str(service.get("name", "")).strip().lower()
            if not service_name:
                continue

            clients = command.get("clients")
            normalized_clients = []
            if isinstance(clients, list):
                normalized_clients = [
                    str(item).strip().lower()
                    for item in clients
                    if str(item).strip()
                ]
            if client_key and normalized_clients and client_key not in normalized_clients and "*" not in normalized_clients:
                continue

            registration_ts = float(service.get("updated_at", 0.0) or 0.0)
            key = (service_name, name)
            candidate = {
                "command": name,
                "title": str(command.get("title", command.get("description", name))).strip() or name,
                "description": str(command.get("description", name)).strip() or name,
                "service": service_name,
                "method": str(command.get("method", "GET")).upper(),
                "path": str(command.get("path", "")).strip(),
                "query_template": command.get("query_template") if isinstance(command.get("query_template"), dict) else {},
                "body_template": command.get("body_template") if isinstance(command.get("body_template"), dict) else {},
                "response_mode": str(command.get("response_mode", "raw_json")).strip().lower(),
                "response_prompt": str(command.get("response_prompt", "")).strip(),
                "arguments_help": str(command.get("arguments_help", "")).strip(),
                "arg_picker": command.get("arg_picker") if isinstance(command.get("arg_picker"), dict) else {},
                "telegram_visible": bool(command.get("telegram_visible", False)),
                "telegram_help_visible": bool(command.get("telegram_help_visible", True)),
                "clients": normalized_clients,
                "_registration_ts": registration_ts,
            }

            existing = discovered_map.get(key)
            if not existing or candidate["_registration_ts"] >= existing.get("_registration_ts", 0.0):
                discovered_map[key] = candidate

    discovered = list(discovered_map.values())
    for item in discovered:
        item.pop("_registration_ts", None)
    discovered.sort(key=lambda item: (
        item.get("service", ""), item.get("command", "")))
    return {"commands": discovered}


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


@app.get("/api/status")
def status():
    services = []
    for service in registry.all_services():
        endpoint = f"{service['base_url'].rstrip('/')}{service.get('health_endpoint', '/health')}"
        item = dict(service)
        try:
            response = requests.get(endpoint, timeout=health_timeout)
            item["health"] = "healthy" if response.status_code < 400 else "degraded"
            item["health_status_code"] = response.status_code
        except requests.RequestException:
            item["health"] = "unavailable"
            item["health_status_code"] = None
        services.append(item)

    return {"services": services}

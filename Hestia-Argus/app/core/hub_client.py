"""Hub client — register Argus with Hub and discover monitored services."""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
ARGUS_SERVICE_BASE_URL = os.getenv(
    "ARGUS_SERVICE_BASE_URL", "http://hestia_argus:19008"
).rstrip("/")


def register() -> bool:
    """Register Argus with the Hub service registry. Returns True on success."""
    payload = {
        "name": "argus",
        "base_url": ARGUS_SERVICE_BASE_URL,
        "version": "1.0.0",
        "service_type": "core",
        "tags": ["core", "monitoring"],
        "capabilities": {
            "argus.status": {
                "description": "Live health snapshot of all Hestia services",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/status",
                "method": "GET",
            },
            "argus.logs": {
                "description": "Recent filtered log events from a service container",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/logs",
                "method": "GET",
                "parameters": {
                    "service": "Optional service name filter",
                    "level": "Minimum log level (WARNING/ERROR/CRITICAL)",
                    "since": "Time window e.g. 30m, 1h",
                },
            },
            "argus.analyze": {
                "description": "Full system analysis combining health and logs",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/analyze",
                "method": "POST",
            },
        },
        "telegram_commands": {
            "system_status": {
                "description": "Show the health status of all Hestia services",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/status",
                "method": "GET",
            },
            "system_logs": {
                "description": "Show recent warning/error log events",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/logs",
                "method": "GET",
            },
        },
    }
    try:
        resp = requests.post(
            f"{HUB_API_URL}/register", json=payload, timeout=10
        )
        resp.raise_for_status()
        logger.info("Argus registered with Hub successfully")
        return True
    except Exception as exc:
        logger.warning("Hub registration failed: %s", exc)
        return False


def discover_services() -> list[dict]:
    """Query Hub registry and return the list of registered services."""
    try:
        resp = requests.get(f"{HUB_API_URL}/registry", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Could not fetch service registry from Hub: %s", exc)
        return []

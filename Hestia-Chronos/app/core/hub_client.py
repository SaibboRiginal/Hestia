"""Hub communication helper — thin wrapper used by the startup registration."""
from __future__ import annotations

import logging
import os
import time

import requests

logger = logging.getLogger("hestia_chronos.hub_client")


def register_on_hub(
    hub_api_url: str,
    service_base_url: str,
    *,
    max_attempts: int = 8,
    retry_delay: float = 2.0,
) -> None:
    """Register this service in Hub with retry logic.

    Declared capabilities include the generic ``calendar.create_event`` and
    ``calendar.list_events`` tool endpoints so that Oracle can discover and
    call them through Hub routing without knowing the specific calendar
    backend in use.
    """
    payload = {
        "name": "chronos",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "integration",
        "service_version": os.getenv("CALENDAR_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "integration"],
        "capabilities": {
            "tool_endpoints": {
                "calendar.create_event": f"{service_base_url}/api/calendar/events",
                "calendar.list_events": f"{service_base_url}/api/calendar/events/list",
            },
            "commands": [
                {
                    "command": "calendar_create",
                    "title": "📅 Crea evento",
                    "description": "Crea un evento nel calendario",
                    "method": "POST",
                    "path": "/api/calendar/events",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "telegram_visible": False,
                },
            ],
        },
    }

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.post(
                f"{hub_api_url}/registry/register", json=payload, timeout=4
            )
            if resp.status_code < 400:
                logger.info(
                    "[HUB] Registered | attempt=%s hub=%s base_url=%s",
                    attempt,
                    hub_api_url,
                    service_base_url,
                )
                return
            logger.warning(
                "[HUB] Registration returned non-success | attempt=%s status=%s",
                attempt,
                resp.status_code,
            )
        except Exception as exc:
            logger.warning(
                "[HUB] Registration attempt %s failed: %s", attempt, exc)

        if attempt < max_attempts:
            time.sleep(retry_delay)

    logger.error("[HUB] All %s registration attempts failed.", max_attempts)

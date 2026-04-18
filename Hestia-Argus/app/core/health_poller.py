"""Health poller — polls /health endpoints for every registered service."""
from __future__ import annotations

import logging
from datetime import datetime

import requests

from schemas.reports import HealthReport

logger = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds per request


def poll_service(service: dict) -> HealthReport:
    """Poll a single service's /health endpoint and return a HealthReport."""
    name = service.get("name", "unknown")
    base_url = service.get("base_url", "").rstrip("/")
    health_url = f"{base_url}/health"
    try:
        resp = requests.get(health_url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            try:
                details = resp.json()
            except Exception:
                details = {"raw": resp.text[:200]}
            return HealthReport(
                service=name,
                status="up",
                details=details,
                checked_at=datetime.utcnow(),
            )
        else:
            return HealthReport(
                service=name,
                status="degraded",
                error=f"HTTP {resp.status_code}",
                checked_at=datetime.utcnow(),
            )
    except requests.exceptions.ConnectionError:
        return HealthReport(
            service=name,
            status="down",
            error="Connection refused",
            checked_at=datetime.utcnow(),
        )
    except Exception as exc:
        return HealthReport(
            service=name,
            status="down",
            error=str(exc),
            checked_at=datetime.utcnow(),
        )


def poll_all(services: list[dict]) -> dict[str, HealthReport]:
    """Poll all services and return a mapping of name → HealthReport."""
    results: dict[str, HealthReport] = {}
    for svc in services:
        name = svc.get("name", "unknown")
        results[name] = poll_service(svc)
    return results

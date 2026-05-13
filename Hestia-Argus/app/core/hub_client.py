"""Hub client — register Argus with Hub and discover monitored services."""
from __future__ import annotations

import logging
import os
from datetime import datetime

import requests

from schemas.reports import LogEvent

logger = logging.getLogger(f"hestia_argus.{__name__}")

HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
ARGUS_SERVICE_BASE_URL = os.getenv(
    "ARGUS_SERVICE_BASE_URL", "http://hestia_argus:19008"
).rstrip("/")


def register(*, quiet_success: bool = False) -> bool:
    """Register Argus with the Hub service registry. Returns True on success."""
    payload = {
        "name": "argus",
        "base_url": ARGUS_SERVICE_BASE_URL,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": "1.0.0",
        "tags": ["core", "monitoring"],
        "topology_tags": ["layer:foundation", "domain:observability", "status:stable"],
        "capabilities": {
            "argus_status": {
                "description": "Live health snapshot of all Hestia services",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/status",
                "method": "GET",
            },
            "argus_logs": {
                "description": "Recent filtered log events from a service container",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/logs",
                "method": "GET",
                "parameters": {
                    "service": "Optional service name filter",
                    "level": "Minimum log level (WARNING/ERROR/CRITICAL)",
                    "since": "Time window e.g. 30m, 1h",
                },
            },
            "argus_analyze": {
                "description": "Full system analysis combining health and logs",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/analyze",
                "method": "POST",
            },
            "argus_remediate": {
                "description": "Create a remediation intent for Hephaestus via Hub-routed contract",
                "endpoint": f"{ARGUS_SERVICE_BASE_URL}/api/argus/remediate",
                "method": "POST",
            },
            "commands": [
                {
                    "command": "system_status",
                    "title": "🖥️ Stato sistema",
                    "description": "Mostra lo stato di salute di tutti i servizi Hestia",
                    "method": "GET",
                    "path": "/api/argus/status",
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Sii ESTREMAMENTE conciso. "
                        "Una riga introduttiva con il conteggio (es. '9/9 servizi online'). "
                        "Poi una lista puntata • con ogni servizio: ✅ nome se up, ❌ nome — motivo se down/degraded. "
                        "Se tutto funziona scrivi solo la riga introduttiva senza lista. "
                        "Nessun paragrafo aggiuntivo, nessuna conclusione."
                    ),
                },
                {
                    "command": "system_log",
                    "title": "📋 Log di sistema",
                    "description": "Mostra gli errori e warning recenti dei servizi",
                    "method": "GET",
                    "path": "/api/argus/logs",
                    "query_template": {"level": "WARNING"},
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Sii ESTREMAMENTE conciso. "
                        "Se non ci sono eventi: una sola frase '✅ Nessun warning recente.' "
                        "Altrimenti: una riga con il totale, poi lista puntata • per ogni problema "
                        "nel formato '• [LIVELLO] servizio — messaggio breve'. "
                        "Raggruppa per servizio se ci sono più eventi dallo stesso. "
                        "Nessun paragrafo introduttivo, nessuna conclusione."
                    ),
                },
                {
                    "command": "system_analysis",
                    "title": "🔍 Analisi sistema",
                    "description": "Esegui un'analisi completa dei servizi con AI",
                    "method": "POST",
                    "path": "/api/argus/analyze",
                    "body_template": {},
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                    "response_prompt": (
                        "Sii conciso e diretto. Struttura SEMPRE così: "
                        "1) Una riga di stato globale (es. '✅ Sistema sano' o '⚠️ X problemi rilevati'). "
                        "2) Se ci sono problemi: lista puntata • con ogni issue — servizio, sintomo, causa probabile. "
                        "3) Se necessario: lista puntata • con azioni suggerite, massimo 3. "
                        "Preferisci liste puntate a paragrafi. Nessun testo introduttivo o di chiusura. "
                        "Usa il campo 'summary' come base per l'analisi AI già elaborata."
                    ),
                },
                {
                    "command": "system_remediate",
                    "title": "Avvia remediation sistema",
                    "description": "Invia un remediation intent ad Hephaestus",
                    "method": "POST",
                    "path": "/api/argus/remediate",
                    "body_template": {
                        "service": "$service",
                        "issue": "$issue",
                        "severity": "$severity",
                        "requested_action": "$requested_action",
                        "environment": "$environment",
                        "dry_run": "$dry_run",
                        "auto_approve": "$auto_approve",
                    },
                    "arguments_schema": {
                        "service": {"type": "string", "required": True, "description": "Service target remediation"},
                        "issue": {"type": "string", "required": True, "description": "Issue summary"},
                        "severity": {"type": "string", "required": False, "description": "warning|error|critical"},
                        "requested_action": {"type": "string", "required": False, "description": "Requested remediation action"},
                        "environment": {"type": "string", "required": False, "description": "dev|staging|prod"},
                        "dry_run": {"type": "boolean", "required": False, "description": "Remediation in dry-run mode"},
                        "auto_approve": {"type": "boolean", "required": False, "description": "Allow policy auto-approval"},
                    },
                    "clients": ["telegram", "ui"],
                    "response_mode": "oracle_natural",
                },
            ],
        },
    }
    try:
        resp = requests.post(
            f"{HUB_API_URL}/registry/register", json=payload, timeout=10
        )
        resp.raise_for_status()
        if quiet_success:
            logger.debug(
                "event=argus_registered_with_hub_successfully Argus registered with Hub successfully")
        else:
            logger.info(
                "event=argus_registered_with_hub_successfully Argus registered with Hub successfully")
        return True
    except Exception as exc:
        logger.warning(
            "event=hub_registration_failed Hub registration failed: %s", exc)
        return False


def discover_services() -> list[dict]:
    """Query Hub registry and return the list of registered services."""
    try:
        resp = requests.get(f"{HUB_API_URL}/registry/services", timeout=10)
        resp.raise_for_status()
        return resp.json().get("services", [])
    except Exception as exc:
        logger.warning(
            "event=could_fetch_service_registry_from Could not fetch service registry from Hub: %s", exc)
        return []


def fetch_service_log_events(
    service_name: str,
    *,
    level: str = "WARNING",
    limit: int = 200,
    contains: str | None = None,
    timeout_seconds: float = 8.0,
) -> list[LogEvent]:
    """Fetch service logs via Hub monitor endpoint and normalize into LogEvent rows."""
    params: dict[str, object] = {
        "mode": "raw",
        "limit": max(1, min(limit, 2000)),
        "level": level,
        "timeout_seconds": timeout_seconds,
    }
    if contains:
        params["contains"] = contains

    try:
        response = requests.get(
            f"{HUB_API_URL}/monitor/logs/{service_name}",
            params=params,
            timeout=max(2.0, timeout_seconds + 2.0),
        )
        response.raise_for_status()
        payload = (response.json() or {}).get("payload") or {}
        rows = payload.get("logs") or []
        if not isinstance(rows, list):
            return []

        events: list[LogEvent] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            events.append(
                LogEvent(
                    timestamp=str(
                        row.get("ts") or datetime.utcnow().isoformat()),
                    service=service_name,
                    container=f"hestia_{service_name}",
                    level=str(row.get("level") or "INFO").upper(),
                    message=str(row.get("formatted") or row.get(
                        "message") or "").strip(),
                )
            )
        return events
    except Exception as exc:
        logger.warning(
            "event=could_fetch_logs_hub_monitor Could not fetch logs via Hub monitor | service=%s error=%s",
            service_name,
            exc,
        )
        return []


def request_hephaestus_remediation(
    *,
    source: str,
    service: str,
    issue: str,
    severity: str = "warning",
    requested_action: str = "runbook_autoselect",
    environment: str = "dev",
    dry_run: bool = True,
    auto_approve: bool = False,
    metadata: dict[str, object] | None = None,
) -> tuple[bool, dict]:
    body = {
        "source": source,
        "service": service,
        "issue": issue,
        "severity": severity,
        "requested_action": requested_action,
        "environment": environment,
        "dry_run": bool(dry_run),
        "auto_approve": bool(auto_approve),
        "metadata": metadata or {},
    }
    envelope = {
        "method": "POST",
        "headers": {},
        "query": {},
        "body": body,
        "timeout_seconds": float(os.getenv("ARGUS_REMEDIATE_TIMEOUT_SECONDS", "15")),
    }
    try:
        response = requests.post(
            f"{HUB_API_URL}/route/hephaestus/api/hephaestus/remediate",
            json=envelope,
            timeout=max(5.0, float(envelope["timeout_seconds"]) + 2.0),
        )
        if response.status_code != 200:
            return False, {
                "status": "error",
                "error": f"hub_route_status_{response.status_code}",
                "detail": response.text[:300],
            }
        routed = response.json() if response.content else {}
        status_code = int((routed or {}).get("status_code", 500))
        payload = (routed or {}).get("payload") if isinstance((routed or {}).get("payload"), dict) else {
            "raw": (routed or {}).get("payload")
        }
        if status_code >= 400:
            return False, {
                "status": "error",
                "error": f"hephaestus_status_{status_code}",
                "payload": payload,
            }
        return True, payload
    except Exception as exc:
        logger.warning(
            "event=argus_hephaestus_remediation_failed Hephaestus remediation request failed: %s", exc)
        return False, {
            "status": "error",
            "error": str(exc),
        }

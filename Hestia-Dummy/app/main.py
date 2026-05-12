from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, AsyncIterator

import requests
from fastapi import FastAPI
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


@dataclass(frozen=True)
class RuntimeConfig:
    service_name: str
    service_base_url: str
    service_version: str
    service_type: str
    service_tags: list[str]
    hub_api_url: str
    port: int
    mutation_delay_ms: int


class MaintenanceRequest(BaseModel):
    source: str = "system"
    task_id: str | None = None
    issue: str | None = None
    requested_action: str | None = "generic_test_reconcile"
    environment: str = "dev"
    dry_run: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


def _load_runtime_config() -> RuntimeConfig:
    service_type = os.getenv("SERVICE_TYPE", "module")
    return RuntimeConfig(
        service_name=os.getenv("SERVICE_NAME", "dummy"),
        service_base_url=os.getenv(
            "SERVICE_BASE_URL", "http://hestia_dummy:19011"),
        service_version=os.getenv("SERVICE_VERSION", "1.0.0"),
        service_type=service_type,
        service_tags=[
            tag.strip().lower()
            for tag in os.getenv("SERVICE_TAGS", service_type).split(",")
            if tag.strip()
        ],
        hub_api_url=os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/"),
        port=int(os.getenv("DUMMY_PORT", "19011")),
        mutation_delay_ms=max(
            0, int(os.getenv("DUMMY_MUTATION_DELAY_MS", "80"))),
    )


def _register_to_hub(config: RuntimeConfig, logger) -> None:
    payload = {
        "name": config.service_name,
        "base_url": config.service_base_url,
        "health_endpoint": "/health",
        "service_type": config.service_type,
        "service_version": config.service_version,
        "tags": config.service_tags,
        "capabilities": {
            "commands": [
                {
                    "command": "dummy_test_reconcile",
                    "title": "Dummy Test Reconcile",
                    "description": "Execute generic reconciliation on the test module",
                    "method": "POST",
                    "path": "/api/module/maintenance/reconcile",
                    "response_mode": "direct",
                    "clients": ["telegram"],
                }
            ]
        },
    }
    requests.post(
        f"{config.hub_api_url}/registry/register",
        json=payload,
        timeout=4,
    )
    logger.info(
        "event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
        config.service_name,
        config.service_base_url,
    )


logger, log_buffer = setup_service_logging("hestia_dummy")
runtime = _load_runtime_config()

_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "status": "ok",
    "last_reconcile_at": None,
    "last_task_id": None,
    "mutation_count": 0,
    "last_environment": None,
    "last_action": None,
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    startup_wait_timeout = float(
        os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))
    wait_for_http_ready(
        hub_health_url(runtime.hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )

    try:
        _register_to_hub(runtime, logger)
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s",
            error,
        )

    def _hub_keepalive() -> None:
        while True:
            time.sleep(60)
            try:
                _register_to_hub(runtime, logger)
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s",
                    error,
                )

    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()
    yield


app = FastAPI(title="Hestia-Dummy",
              version=runtime.service_version, lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": runtime.service_name}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None) -> dict[str, Any]:
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_dummy",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/dummy/status")
def dummy_status() -> dict[str, Any]:
    with _state_lock:
        snapshot = dict(_state)
    return {"status": "ok", "service": runtime.service_name, "state": snapshot}


def _apply_reconcile(req: MaintenanceRequest) -> dict[str, Any]:
    with _state_lock:
        now = datetime.now(timezone.utc).isoformat()
        actions = [
            {
                "id": "health_probe",
                "title": "Validate generic test module state",
                "result": "ok",
            },
            {
                "id": "cache_refresh",
                "title": "Refresh deterministic testing cache",
                "result": "ok",
            },
        ]
        if req.dry_run:
            return {
                "status": "ok",
                "service": runtime.service_name,
                "dry_run": True,
                "task_id": req.task_id,
                "executed_at": now,
                "actions": actions,
                "note": "Preview only. No mutation applied.",
                "state": dict(_state),
            }

        if runtime.mutation_delay_ms:
            time.sleep(runtime.mutation_delay_ms / 1000.0)

        _state["last_reconcile_at"] = now
        _state["last_task_id"] = req.task_id
        _state["last_environment"] = req.environment
        _state["last_action"] = req.requested_action
        _state["mutation_count"] = int(_state.get("mutation_count", 0)) + 1

        return {
            "status": "ok",
            "service": runtime.service_name,
            "dry_run": False,
            "task_id": req.task_id,
            "executed_at": now,
            "actions": actions,
            "note": "Mutation applied to dummy module state.",
            "state": dict(_state),
        }


@app.post("/api/module/maintenance/reconcile")
def module_maintenance_reconcile(req: MaintenanceRequest) -> dict[str, Any]:
    result = _apply_reconcile(req)
    logger.info(
        "event=dummy_reconcile_completed task_id=%s dry_run=%s mutation_count=%s",
        req.task_id or "",
        str(req.dry_run).lower(),
        str((result.get("state") or {}).get("mutation_count") or 0),
    )
    return result


@app.post("/api/maintenance/reconcile")
def maintenance_reconcile_alias(req: MaintenanceRequest) -> dict[str, Any]:
    return module_maintenance_reconcile(req)

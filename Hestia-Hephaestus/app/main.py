from __future__ import annotations

import threading
import time
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from .api.hephaestus_router import create_hephaestus_router
from .core.remediation_service import RemediationService
from .core.service import HephaestusService
from .core.service_contract import ServiceDescriptor
from .core.service_runtime import load_runtime_config
from .core.shared_imports import import_shared_symbol

setup_service_logging = import_shared_symbol(
    "hestia_common.logging_utils",
    "setup_service_logging",
)

hub_health_url = import_shared_symbol(
    "hestia_common.startup_utils",
    "hub_health_url",
)

wait_for_http_ready = import_shared_symbol(
    "hestia_common.startup_utils",
    "wait_for_http_ready",
)

logger, log_buffer = setup_service_logging("hestia_hephaestus")
config = load_runtime_config()

service = HephaestusService(
    ServiceDescriptor(
        name=config.service_name,
        base_url=config.service_base_url,
        service_type=config.service_type,
        service_version=config.service_version,
        tags=config.service_tags,
        topology_tags=config.service_topology_tags,
    )
)

remediation_service = RemediationService(
    logger=logger,
    hub_api_url=config.hub_api_url,
    hermes_api_url=config.hermes_api_url,
    notify_target=config.hephaestus_notify_target,
    baseline_ref=config.hephaestus_baseline_ref,
    execution_timeout_seconds=config.hephaestus_execution_timeout_seconds,
    require_approval_for_mutation=config.hephaestus_require_approval_for_mutation,
    allow_auto_approve_non_prod=config.hephaestus_allow_auto_approve_non_prod,
    maintenance_paths=config.hephaestus_maintenance_paths,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    startup_wait_timeout = 0.0
    try:
        startup_wait_timeout = float(
            os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))
    except Exception:
        startup_wait_timeout = 0.0

    wait_for_http_ready(
        hub_health_url(config.hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )

    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info(
            "event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
            config.service_name,
            config.service_base_url,
        )
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s",
            error,
        )

    def _hub_keepalive() -> None:
        while True:
            time.sleep(60)
            try:
                service.register_to_hub(timeout_seconds=4)
            except Exception as error:
                logger.warning(
                    "event=hub_keepalive_registration_failed Hub keepalive registration failed: %s",
                    error,
                )

    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()
    yield


app = FastAPI(title="Hestia Hephaestus",
              version=config.service_version, lifespan=lifespan)
app.include_router(create_hephaestus_router(remediation_service))


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": config.service_name,
        "version": config.service_version,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None) -> dict[str, Any]:
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_hephaestus",
        "count": len(rows),
        "logs": rows,
    }

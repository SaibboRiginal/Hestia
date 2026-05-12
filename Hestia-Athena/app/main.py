import os
import threading
from typing import Any

from fastapi import FastAPI, HTTPException

from .core.runtime import AthenaRuntime
from .core.schemas import CommitmentResolveRequest, TriggerRequest
from .core.service_contract import HestiaServiceBase, ServiceDescriptor
from .core.shared_imports import import_shared_symbol

setup_service_logging = import_shared_symbol(
    "hestia_common.logging_utils", "setup_service_logging"
)
logger, log_buffer = setup_service_logging("hestia_athena")


class AthenaService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        return {
            "focus_brief_loop": True,
            "relevance_gate_fields": [
                "urgency",
                "usefulness",
                "novelty",
                "interruption_cost",
                "confidence",
            ],
            "retrospective_inputs": [
                "recent_outcomes",
                "repeated_failures",
                "unresolved_commitments",
            ],
            "event_emit_endpoint": "/api/events/ingest",
            "oracle_hint_route": "/api/athena/hints",
            "status_endpoint": "/api/athena/status",
            "manual_trigger_endpoint": "/api/athena/trigger",
            "commitments_endpoint": "/api/athena/commitments",
        }


_HUB_KEEPALIVE_SECONDS = max(60, int(os.getenv("HUB_KEEPALIVE_SECONDS", "60")))
_hub_keepalive_stop = threading.Event()
_hub_keepalive_thread: threading.Thread | None = None


def _register_on_hub() -> None:
    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info(
            "event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
            SERVICE_NAME,
            SERVICE_BASE_URL,
        )
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s",
            error,
        )


def _hub_keepalive_loop() -> None:
    while not _hub_keepalive_stop.wait(_HUB_KEEPALIVE_SECONDS):
        _register_on_hub()


def _start_hub_keepalive() -> None:
    global _hub_keepalive_thread
    if _hub_keepalive_thread and _hub_keepalive_thread.is_alive():
        return
    _hub_keepalive_stop.clear()
    _hub_keepalive_thread = threading.Thread(
        target=_hub_keepalive_loop,
        daemon=True,
        name="athena-hub-keepalive",
    )
    _hub_keepalive_thread.start()


def _stop_hub_keepalive() -> None:
    _hub_keepalive_stop.set()


SERVICE_NAME = os.getenv("SERVICE_NAME", "athena")
SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://hestia_athena:19009")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", SERVICE_TYPE).split(",")
    if tag.strip()
]

service = AthenaService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
    )
)
runtime = AthenaRuntime()

app = FastAPI(title="Hestia Athena", version=SERVICE_VERSION)


@app.on_event("startup")
def startup() -> None:
    logger.info(
        "event=service_startup service=%s version=%s",
        SERVICE_NAME,
        SERVICE_VERSION,
    )
    _register_on_hub()
    _start_hub_keepalive()
    runtime.start()


@app.on_event("shutdown")
def shutdown() -> None:
    logger.info("event=service_shutdown service=%s", SERVICE_NAME)
    runtime.stop()
    _stop_hub_keepalive()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_athena",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/athena/status")
def athena_status() -> dict[str, Any]:
    return {"status": "ok", "runtime": runtime.status()}


@app.post("/api/athena/trigger")
def athena_trigger(request: TriggerRequest) -> dict[str, Any]:
    return runtime.trigger(request)


@app.get("/api/athena/tasks")
def athena_tasks(
    limit: int = 100,
    task_type: str | None = None,
    lifecycle_state: str | None = None,
) -> dict[str, Any]:
    rows = runtime.list_tasks(
        limit=limit,
        task_type=task_type,
        lifecycle_state=lifecycle_state,
    )
    return {
        "status": "ok",
        "count": len(rows),
        "tasks": rows,
    }


@app.get("/api/athena/tasks/{task_id}")
def athena_task(task_id: str) -> dict[str, Any]:
    row = runtime.get_task(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail=f"task '{task_id}' not found")
    return {
        "status": "ok",
        "task": row,
    }


@app.get("/api/athena/commitments")
def athena_commitments(
    limit: int = 100,
    include_resolved: bool = False,
) -> dict[str, Any]:
    rows = runtime.list_commitments(
        limit=limit,
        include_resolved=include_resolved,
    )
    return {
        "status": "ok",
        "count": len(rows),
        "commitments": rows,
    }


@app.post("/api/athena/commitments/{brief_id}/resolve")
def resolve_athena_commitment(brief_id: str, request: CommitmentResolveRequest) -> dict[str, Any]:
    row = runtime.resolve_commitment(
        brief_id=brief_id,
        status=request.status,
        note=request.note,
    )
    if not row:
        raise HTTPException(
            status_code=404, detail=f"commitment '{brief_id}' not found")
    return {
        "status": "ok",
        "commitment": row,
    }

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
create_log_control_router = import_shared_symbol(
    "hestia_common.logging_utils", "create_log_control_router"
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
            "observation_sources": [
                "hub_registry",
                "argus_health",
                "archive_entities",
                "self_state",
            ],
            "thinking_modules": [
                "observer",
                "strategist",
            ],
            "event_emit_endpoint": "/api/events/ingest",
            "oracle_hint_route": "/api/athena/hints",
            "status_endpoint": "/api/athena/status",
            "manual_trigger_endpoint": "/api/athena/trigger",
            "commitments_endpoint": "/api/athena/commitments",
            "thinking_endpoint": "/api/athena/thinking",
            "observation_endpoint": "/api/athena/observation",
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
SERVICE_TOPOLOGY_TAGS = [
    tag.strip().lower()
    for tag in os.getenv(
        "SERVICE_TOPOLOGY_TAGS",
        "layer:cognition,domain:strategy,status:beta",
    ).split(",")
    if tag.strip()
]

service = AthenaService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
        topology_tags=SERVICE_TOPOLOGY_TAGS,
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


@app.get("/api/athena/thinking")
def athena_thinking(
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent thinking records — observation → candidates → decisions.

    Each record shows what Athena observed, what it considered doing,
    and what it actually emitted. This is the audit trail for proactive
    cognition that a client can display to show "what Athena is thinking."
    """
    rows = runtime.list_thinking_records(limit=limit)
    return {
        "status": "ok",
        "count": len(rows),
        "thinking": rows,
    }


@app.get("/api/athena/observation")
def athena_observation() -> dict[str, Any]:
    """Return the most recent observation snapshot.

    Shows live system state as last seen by Athena: registered services,
    unhealthy services, domain entity summaries, and self-state.
    """
    snapshot = runtime._observe()
    return {
        "status": "ok",
        "observation": snapshot.model_dump(),
    }


# ── MCP tools ──────────────────────────────────────────────────────────────────
try:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router
    from .core.auditor import ConversationAuditor

    _ATHENA_HUB_URL = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

    def _athena_audit_handler(
        session_id: str = "",
        limit: int = 20,
    ) -> dict:
        """Run a quality audit on recent conversation turns."""
        auditor = ConversationAuditor(_ATHENA_HUB_URL)
        result = auditor.audit_session(
            session_id=str(session_id or "").strip(),
            limit=int(limit) if limit else 20,
        )
        return result

    _athena_mcp_tools = [
        MCPTool(
            name="athena_audit_conversation",
            description=(
                "Run a quality audit on recent conversation turns using the "
                "26B reasoning model. Scores style adherence, accuracy, and "
                "usefulness for each assistant turn. Persists scores via "
                "Archive's feedback_submit. On-demand only — no automated loop."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session identifier to audit",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Max conversation turns to pull (default 20)",
                    },
                },
                "required": ["session_id"],
            },
            handler=_athena_audit_handler,
            title="🔍 Audita conversazione",
            method="POST",
            path="/api/athena/audit/conversation",
            clients=["telegram", "ui"],
            response_mode="oracle_natural",
            response_prompt=(
                "Riporta i risultati dell'audit in modo chiaro: numero di "
                "risposte valutate e distribuzione dei punteggi per stile, "
                "accuratezza e utilità. Sii conciso."
            ),
            telegram_visible=True,
            telegram_group="chat",
        ),
    ]
    app.include_router(
        create_mcp_router(_athena_mcp_tools, service_name="athena")
    )
    logger.info(
        "event=mcp_router_mounted service=athena tools=%d",
        len(_athena_mcp_tools),
    )
except ModuleNotFoundError:
    logger.info(
        "event=mcp_router_skipped service=athena "
        "reason=hestia_common_not_available"
    )

app.include_router(create_log_control_router("hestia_athena"))

import logging
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .core.service_contract import HestiaServiceBase, ServiceDescriptor

try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging

logger, log_buffer = setup_service_logging("hestia_hephaestus")


class ConsentTier(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class RunbookStep(BaseModel):
    id: str
    title: str
    kind: str
    read_only: bool = True
    rollback_checkpoint: str | None = None


class RunbookDefinition(BaseModel):
    runbook_id: str
    title: str
    summary: str
    consent_tier: ConsentTier
    default_dry_run: bool = True
    production_allowed: bool = False
    steps: list[RunbookStep]


class DiagnosticsRequest(BaseModel):
    target: str = "hestia"
    issue: str = "generic_diagnostics"
    context: dict[str, Any] = Field(default_factory=dict)
    requested_consent_tier: ConsentTier = ConsentTier.none
    dry_run: bool = True
    environment: str = "dev"


class ExecutePreviewRequest(BaseModel):
    runbook_id: str
    consent_tier: ConsentTier
    dry_run: bool = True
    environment: str = "dev"


class HephaestusService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        return {
            "runbook_first": True,
            "read_only_mvp": True,
            "self_healing_runbooks": True,
            "consent_tiers": [tier.value for tier in ConsentTier],
            "dry_run_default": True,
            "rollback_checkpoints": True,
            "production_execution_allowed": False,
            "endpoints": {
                "runbooks": "/api/hephaestus/runbooks",
                "diagnose": "/api/hephaestus/diagnose",
                "execute_preview": "/api/hephaestus/execute-preview",
                "status": "/api/hephaestus/status",
            },
        }


RUNBOOKS: dict[str, RunbookDefinition] = {
    "rbk_service_health_triage": RunbookDefinition(
        runbook_id="rbk_service_health_triage",
        title="Service health triage",
        summary="Read-only diagnostics for container status, health endpoints, and recent logs.",
        consent_tier=ConsentTier.low,
        default_dry_run=True,
        production_allowed=False,
        steps=[
            RunbookStep(
                id="step_1",
                title="Collect container and process status",
                kind="inspect",
                read_only=True,
                rollback_checkpoint="status_snapshot",
            ),
            RunbookStep(
                id="step_2",
                title="Check service health endpoints",
                kind="probe",
                read_only=True,
                rollback_checkpoint="health_snapshot",
            ),
            RunbookStep(
                id="step_3",
                title="Capture relevant recent logs",
                kind="observe",
                read_only=True,
                rollback_checkpoint="log_snapshot",
            ),
        ],
    ),
    "rbk_config_integrity_review": RunbookDefinition(
        runbook_id="rbk_config_integrity_review",
        title="Config integrity review",
        summary="Validate environment and configuration consistency without mutating state.",
        consent_tier=ConsentTier.medium,
        default_dry_run=True,
        production_allowed=False,
        steps=[
            RunbookStep(
                id="step_1",
                title="Read active config surfaces",
                kind="inspect",
                read_only=True,
                rollback_checkpoint="config_snapshot",
            ),
            RunbookStep(
                id="step_2",
                title="Compare config against runbook expectations",
                kind="analyze",
                read_only=True,
                rollback_checkpoint="analysis_snapshot",
            ),
        ],
    ),
    "rbk_service_self_heal_recovery": RunbookDefinition(
        runbook_id="rbk_service_self_heal_recovery",
        title="Service self-heal recovery",
        summary="Guarded restart and dependency recovery plan with mandatory rollback checkpoints.",
        consent_tier=ConsentTier.high,
        default_dry_run=True,
        production_allowed=False,
        steps=[
            RunbookStep(
                id="step_1",
                title="Capture pre-heal state snapshot (health, logs, env)",
                kind="observe",
                read_only=True,
                rollback_checkpoint="pre_heal_snapshot",
            ),
            RunbookStep(
                id="step_2",
                title="Plan scoped service restart and dependency refresh",
                kind="plan",
                read_only=False,
                rollback_checkpoint="restart_plan_snapshot",
            ),
            RunbookStep(
                id="step_3",
                title="Define rollback procedure and post-heal verification checks",
                kind="rollback_plan",
                read_only=True,
                rollback_checkpoint="rollback_plan_snapshot",
            ),
        ],
    ),
}


def _select_runbook(issue: str) -> RunbookDefinition:
    issue_lc = issue.lower()
    if any(token in issue_lc for token in ["self-heal", "self_heal", "recover", "restart", "crash", "oom", "stuck"]):
        return RUNBOOKS["rbk_service_self_heal_recovery"]
    if any(token in issue_lc for token in ["config", "env", "setting"]):
        return RUNBOOKS["rbk_config_integrity_review"]
    return RUNBOOKS["rbk_service_health_triage"]


def _consent_allows(requested: ConsentTier, required: ConsentTier) -> bool:
    order = {
        ConsentTier.none: 0,
        ConsentTier.low: 1,
        ConsentTier.medium: 2,
        ConsentTier.high: 3,
    }
    return order[requested] >= order[required]


def _build_self_heal_preview(runbook: RunbookDefinition, request: DiagnosticsRequest) -> dict[str, Any]:
    mutating_steps = [step for step in runbook.steps if not step.read_only]
    needs_high_consent = runbook.consent_tier in {
        ConsentTier.medium, ConsentTier.high}
    return {
        "mode": "preview_only",
        "mutating_step_count": len(mutating_steps),
        "requires_human_approval": len(mutating_steps) > 0,
        "requires_high_consent": needs_high_consent,
        "dry_run": request.dry_run,
        "environment": request.environment,
        "proposed_remediation": [
            {
                "step_id": step.id,
                "title": step.title,
                "kind": step.kind,
                "read_only": step.read_only,
                "rollback_checkpoint": step.rollback_checkpoint,
            }
            for step in runbook.steps
        ],
    }


SERVICE_NAME = os.getenv("SERVICE_NAME", "hephaestus")
SERVICE_BASE_URL = os.getenv(
    "SERVICE_BASE_URL", "http://hestia_hephaestus:19010")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "core")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", SERVICE_TYPE).split(",")
    if tag.strip()
]

service = HephaestusService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
    )
)

app = FastAPI(title="Hestia Hephaestus", version=SERVICE_VERSION)


@app.on_event("startup")
def register_on_hub_startup() -> None:
    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info("event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
                    SERVICE_NAME, SERVICE_BASE_URL)
    except Exception as error:
        logger.warning("event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", error)


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
        "service": "hestia_hephaestus",
        "count": len(rows),
        "logs": rows,
    }


@app.get("/api/hephaestus/status")
def status() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "read_only_diagnostics",
        "production_execution_allowed": False,
        "self_healing_preview_only": True,
        "runbook_count": len(RUNBOOKS),
    }


@app.get("/api/hephaestus/runbooks")
def list_runbooks() -> dict[str, Any]:
    return {
        "status": "ok",
        "runbooks": [runbook.model_dump() for runbook in RUNBOOKS.values()],
    }


@app.get("/api/hephaestus/runbooks/{runbook_id}")
def get_runbook(runbook_id: str) -> dict[str, Any]:
    runbook = RUNBOOKS.get(runbook_id)
    if not runbook:
        return {
            "status": "error",
            "error": f"Unknown runbook_id: {runbook_id}",
        }
    return {
        "status": "ok",
        "runbook": runbook.model_dump(),
    }


@app.post("/api/hephaestus/diagnose")
def diagnose(request: DiagnosticsRequest) -> dict[str, Any]:
    runbook = _select_runbook(request.issue)
    consent_ok = _consent_allows(
        request.requested_consent_tier, runbook.consent_tier)
    analysis_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    return {
        "status": "ok",
        "analysis_id": analysis_id,
        "created_at": now,
        "target": request.target,
        "issue": request.issue,
        "selected_runbook": runbook.model_dump(),
        "guardrails": {
            "runbook_first": True,
            "read_only": True,
            "dry_run": request.dry_run,
            "production_allowed": False,
            "consent_required": runbook.consent_tier.value,
            "consent_received": request.requested_consent_tier.value,
            "consent_ok": consent_ok,
        },
        "self_healing_preview": _build_self_heal_preview(runbook, request),
        "proposed_actions": [
            {
                "step_id": step.id,
                "title": step.title,
                "mode": "observe_only",
                "rollback_checkpoint": step.rollback_checkpoint,
            }
            for step in runbook.steps
        ],
        "note": "Read-only MVP: diagnostics and plan generation only. No mutating execution.",
    }


@app.post("/api/hephaestus/execute-preview")
def execute_preview(request: ExecutePreviewRequest) -> dict[str, Any]:
    runbook = RUNBOOKS.get(request.runbook_id)
    if not runbook:
        return {
            "status": "error",
            "error": f"Unknown runbook_id: {request.runbook_id}",
        }

    consent_ok = _consent_allows(request.consent_tier, runbook.consent_tier)
    blocked_reasons: list[str] = []
    if request.environment.lower() == "prod":
        blocked_reasons.append("Production execution is disabled in MVP")
    if not request.dry_run:
        blocked_reasons.append("Mutating execution is disabled in MVP")
    if not consent_ok:
        blocked_reasons.append(
            f"Insufficient consent tier: required {runbook.consent_tier.value}, got {request.consent_tier.value}"
        )

    mutating_steps = [step for step in runbook.steps if not step.read_only]

    return {
        "status": "ok",
        "runbook_id": runbook.runbook_id,
        "execution_mode": "preview_only",
        "allowed": len(blocked_reasons) == 0,
        "blocked_reasons": blocked_reasons,
        "requires_human_approval": len(mutating_steps) > 0,
        "mutating_step_count": len(mutating_steps),
        "dry_run": request.dry_run,
        "environment": request.environment,
        "steps": [step.model_dump() for step in runbook.steps],
        "note": "Execution endpoint intentionally returns previews only in P3-1 guarded self-healing mode.",
    }

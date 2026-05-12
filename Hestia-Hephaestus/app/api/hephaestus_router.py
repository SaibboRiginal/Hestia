from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter

from ..core.models import (
    DiagnosticsRequest,
    ExecutePreviewRequest,
    RemediationApproveRequest,
    RemediationRequest,
    RemediationRollbackRequest,
)
from ..core.remediation_service import RemediationService
from ..core.runbooks import RUNBOOKS, build_self_heal_preview, consent_allows, select_runbook


def create_hephaestus_router(remediation_service: RemediationService) -> APIRouter:
    router = APIRouter()

    @router.get("/api/hephaestus/status")
    def status() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "policy_gated_execution",
            "production_execution_allowed": False,
            "self_healing_preview_only": False,
            "runbook_count": len(RUNBOOKS),
        }

    @router.get("/api/hephaestus/runbooks")
    def list_runbooks() -> dict[str, Any]:
        return {
            "status": "ok",
            "runbooks": [runbook.model_dump() for runbook in RUNBOOKS.values()],
        }

    @router.get("/api/hephaestus/runbooks/{runbook_id}")
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

    @router.post("/api/hephaestus/diagnose")
    def diagnose(request: DiagnosticsRequest) -> dict[str, Any]:
        runbook = select_runbook(request.issue)
        consent_ok = consent_allows(
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
            "self_healing_preview": build_self_heal_preview(runbook, request),
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

    @router.post("/api/hephaestus/execute-preview")
    def execute_preview(request: ExecutePreviewRequest) -> dict[str, Any]:
        runbook = RUNBOOKS.get(request.runbook_id)
        if not runbook:
            return {
                "status": "error",
                "error": f"Unknown runbook_id: {request.runbook_id}",
            }

        consent_ok = consent_allows(request.consent_tier, runbook.consent_tier)
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

    @router.get("/api/hephaestus/tasks")
    def list_tasks(limit: int = 100, state: str | None = None) -> dict[str, Any]:
        tasks = remediation_service.list_tasks(limit=limit, state=state)
        return {
            "status": "ok",
            "count": len(tasks),
            "tasks": tasks,
        }

    @router.get("/api/hephaestus/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = remediation_service.get_task(task_id)
        if not task:
            return {
                "status": "error",
                "error": f"Unknown task_id: {task_id}",
            }
        return {
            "status": "ok",
            "task": task,
        }

    @router.post("/api/hephaestus/remediate")
    def remediate(request: RemediationRequest) -> dict[str, Any]:
        runbook = select_runbook(request.issue)
        task = remediation_service.create_task(request, runbook)
        return {
            "status": "ok",
            "task": task,
            "approval_required": task["state"] == "pending_approval",
        }

    @router.post("/api/hephaestus/remediate/{task_id}/approve")
    def approve_remediation(task_id: str, request: RemediationApproveRequest) -> dict[str, Any]:
        existing = remediation_service.get_task(task_id)
        if not existing:
            return {
                "status": "error",
                "error": f"Unknown task_id: {task_id}",
            }
        if str(existing.get("state") or "") in {"succeeded", "rolled_back"}:
            return {
                "status": "ok",
                "task": existing,
                "note": "Task already completed; no-op.",
            }
        task = remediation_service.approve_task(task_id, request)
        return {
            "status": "ok",
            "task": task,
        }

    @router.post("/api/hephaestus/remediate/{task_id}/rollback")
    def rollback_remediation(task_id: str, request: RemediationRollbackRequest) -> dict[str, Any]:
        task = remediation_service.rollback_task(task_id, request)
        if not task:
            return {
                "status": "error",
                "error": f"Unknown task_id: {task_id}",
            }
        return {
            "status": "ok",
            "task": task,
        }

    return router

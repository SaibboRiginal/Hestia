from __future__ import annotations

from typing import Any

from .models import ConsentTier, DiagnosticsRequest, RunbookDefinition, RunbookStep


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


def select_runbook(issue: str) -> RunbookDefinition:
    issue_lc = issue.lower()
    if any(token in issue_lc for token in ["self-heal", "self_heal", "recover", "restart", "crash", "oom", "stuck"]):
        return RUNBOOKS["rbk_service_self_heal_recovery"]
    if any(token in issue_lc for token in ["config", "env", "setting"]):
        return RUNBOOKS["rbk_config_integrity_review"]
    return RUNBOOKS["rbk_service_health_triage"]


def consent_allows(requested: ConsentTier, required: ConsentTier) -> bool:
    order = {
        ConsentTier.none: 0,
        ConsentTier.low: 1,
        ConsentTier.medium: 2,
        ConsentTier.high: 3,
    }
    return order[requested] >= order[required]


def build_self_heal_preview(runbook: RunbookDefinition, request: DiagnosticsRequest) -> dict[str, Any]:
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

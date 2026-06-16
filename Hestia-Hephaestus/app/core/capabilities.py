from __future__ import annotations

from typing import Any

from .models import ConsentTier


def build_capabilities() -> dict[str, Any]:
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
            "tasks": "/api/hephaestus/tasks",
            "remediate": "/api/hephaestus/remediate",
            "remediate_approve": "/api/hephaestus/remediate/{task_id}/approve",
            "remediate_rollback": "/api/hephaestus/remediate/{task_id}/rollback",
        },
    }

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
        "commands": [
            {
                "command": "hephaestus_status",
                "title": "Hephaestus stato",
                "description": "Mostra lo stato del motore di remediation",
                "method": "GET",
                "path": "/api/hephaestus/status",
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
            },
            {
                "command": "hephaestus_tasks",
                "title": "Hephaestus task remediation",
                "description": "Lista task remediation recenti",
                "method": "GET",
                "path": "/api/hephaestus/tasks",
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
            },
            {
                "command": "hephaestus_remediate",
                "title": "Avvia remediation",
                "description": "Crea un task remediation policy-gated",
                "method": "POST",
                "path": "/api/hephaestus/remediate",
                "body_template": {
                    "source": "$source",
                    "service": "$service",
                    "issue": "$issue",
                    "severity": "$severity",
                    "requested_action": "$requested_action",
                    "environment": "$environment",
                    "dry_run": "$dry_run",
                    "auto_approve": "$auto_approve",
                },
                "arguments_schema": {
                    "source": {"type": "string", "required": False, "description": "Origine richiesta (argus/oracle/user)"},
                    "service": {"type": "string", "required": True, "description": "Servizio target"},
                    "issue": {"type": "string", "required": True, "description": "Incidente rilevato"},
                    "severity": {"type": "string", "required": False, "description": "warning|error|critical"},
                    "requested_action": {"type": "string", "required": False, "description": "Azione richiesta"},
                    "environment": {"type": "string", "required": False, "description": "dev|staging|prod"},
                    "dry_run": {"type": "boolean", "required": False, "description": "Esecuzione dry-run"},
                    "auto_approve": {"type": "boolean", "required": False, "description": "Auto-approvazione policy-gated"},
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
            },
            {
                "command": "hephaestus_approve",
                "title": "Approva remediation",
                "description": "Approva ed esegue un task remediation pendente",
                "method": "POST",
                "path": "/api/hephaestus/remediate/$task_id/approve",
                "body_template": {
                    "approved_by": "$approved_by",
                    "note": "$note",
                },
                "arguments_schema": {
                    "task_id": {"type": "string", "required": True, "description": "Task remediation ID"},
                    "approved_by": {"type": "string", "required": False, "description": "Attore approvatore"},
                    "note": {"type": "string", "required": False, "description": "Nota approvazione"},
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
            },
            {
                "command": "hephaestus_rollback",
                "title": "Rollback remediation",
                "description": "Esegue rollback logico di un task remediation",
                "method": "POST",
                "path": "/api/hephaestus/remediate/$task_id/rollback",
                "body_template": {
                    "requested_by": "$requested_by",
                    "reason": "$reason",
                },
                "arguments_schema": {
                    "task_id": {"type": "string", "required": True, "description": "Task remediation ID"},
                    "requested_by": {"type": "string", "required": False, "description": "Attore rollback"},
                    "reason": {"type": "string", "required": False, "description": "Motivazione rollback"},
                },
                "clients": ["telegram", "ui"],
                "response_mode": "oracle_natural",
            },
        ],
    }

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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


class RemediationRequest(BaseModel):
    source: str = "argus"
    incident_id: str = Field(default_factory=lambda: str(uuid4()))
    service: str = "unknown"
    issue: str = "generic_incident"
    severity: str = "warning"
    requested_action: str = "runbook_autoselect"
    environment: str = "dev"
    dry_run: bool = True
    auto_approve: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemediationApproveRequest(BaseModel):
    approved_by: str = "operator"
    note: str | None = None
    dry_run_override: bool | None = None


class RemediationRollbackRequest(BaseModel):
    requested_by: str = "operator"
    reason: str = "manual_rollback"

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class RelevanceSignals(BaseModel):
    urgency: float = Field(default=0.3, ge=0.0, le=1.0)
    usefulness: float = Field(default=0.6, ge=0.0, le=1.0)
    novelty: float = Field(default=0.5, ge=0.0, le=1.0)
    interruption_cost: float = Field(default=0.2, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class TriggerRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    domain: str = "cognition"
    signals: RelevanceSignals = Field(default_factory=RelevanceSignals)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommitmentResolveRequest(BaseModel):
    status: str = "resolved"
    note: str | None = None


# ── Observation models ──────────────────────────────────────────────────────────


class ServiceSnapshot(BaseModel):
    """Lightweight view of one registered service."""
    name: str = ""
    base_url: str = ""
    service_type: str = ""
    status: str = "unknown"
    tags: list[str] = Field(default_factory=list)
    topology_tags: list[str] = Field(default_factory=list)
    managed_domain: str | None = None  # derived from topology tag domain:X


class DomainEntitySummary(BaseModel):
    """Counts and recent activity for one entity domain (e.g. real_estate)."""
    domain: str = ""
    total_entities: int = 0
    recent_count: int = 0  # entities updated in the observation window
    pending_count: int = 0  # entities with pending steps
    sample_titles: list[str] = Field(default_factory=list)


class ObservationSnapshot(BaseModel):
    """What Athena observed in one thinking cycle."""
    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    observed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    services: list[ServiceSnapshot] = Field(default_factory=list)
    unhealthy_services: list[str] = Field(default_factory=list)
    domains: list[DomainEntitySummary] = Field(default_factory=list)
    active_commitments: int = 0
    unresolved_commitments: int = 0
    recent_failures: int = 0
    failure_streak: int = 0
    raw_errors: list[str] = Field(default_factory=list)


# ── Action / thinking models ───────────────────────────────────────────────────


class ActionCandidate(BaseModel):
    """A single action Athena is considering."""
    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    domain: str = "cognition"
    title: str = ""
    summary: str = ""
    kind: str = "advisory"  # advisory | remediation | notification | maintenance
    target_service: str | None = None
    target_path: str | None = None
    priority: str = "normal"  # low | normal | elevated | high
    reasoning: str = ""
    signals: RelevanceSignals = Field(default_factory=RelevanceSignals)
    score: float = 0.0
    accepted: bool = False


class ThinkingRecord(BaseModel):
    """Complete record of one Athena thinking cycle — archived for audit."""
    record_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    cycle_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    trigger: str = "periodic"  # periodic | manual
    observation: ObservationSnapshot = Field(default_factory=ObservationSnapshot)
    candidates: list[ActionCandidate] = Field(default_factory=list)
    emitted_count: int = 0
    hint_published: bool = False
    error: str | None = None

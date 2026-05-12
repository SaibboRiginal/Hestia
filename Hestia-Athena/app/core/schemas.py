from __future__ import annotations

from typing import Any

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

# --- Argus schemas ---
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthReport(BaseModel):
    service: str
    status: str                    # "up" | "down" | "degraded"
    checked_at: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] = {}
    error: str | None = None
    ms: int | None = None          # /health response time (performance page, Cindy D16)


class LogEvent(BaseModel):
    timestamp: str
    service: str
    container: str
    level: str                     # WARNING | ERROR | CRITICAL
    message: str


class ServiceAlert(BaseModel):
    triggered_at: datetime = Field(default_factory=datetime.utcnow)
    service: str
    kind: str                      # "health" | "log" | "performance"
    level: str                     # WARNING | ERROR | CRITICAL | DOWN
    message: str
    metric: str | None = None      # performance: memory | cpu | response | storage_size | storage_growth


class SystemReport(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    health_snapshot: dict[str, HealthReport] = {}
    healthy_count: int = 0
    unhealthy_count: int = 0
    recent_events: list[LogEvent] = []
    summary: str = ""

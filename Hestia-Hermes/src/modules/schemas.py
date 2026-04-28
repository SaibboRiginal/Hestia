from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EventIngestRequest(BaseModel):
    event_type: str
    domain: str
    entity_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    event_ts: datetime | None = None


class DispatchSendRequest(BaseModel):
    channel: str
    target: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Subscription(BaseModel):
    id: str
    owner: str
    domain: str
    event_type: str
    filters: dict[str, Any] = Field(default_factory=dict)
    channels: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True


class OutboundEventStateUpdateRequest(BaseModel):
    outbound_event_id: str
    lifecycle_state: str
    detail: str | None = None
    superseded_by: str | None = None

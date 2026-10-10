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
    """Legacy direct send: target ``owner`` → every client; a concrete target on
    a named client (e.g. Forge requester's chat) → only that client."""
    channel: str = ""
    target: str = "owner"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] | None = None


class NotificationClientRequest(BaseModel):
    client: str


class NotificationSeenAllRequest(BaseModel):
    client: str
    # Only notifications this client actually showed (Telegram: user wrote in the chat).
    delivered_to: str | None = None


class NotificationAnswerRequest(BaseModel):
    action_id: str
    client: str


class NotificationOutcomeRequest(BaseModel):
    client: str
    ok: bool = True
    text: str = ""


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

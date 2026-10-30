"""Calendar event schemas shared across the service."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class CalendarEvent(BaseModel):
    """Provider-agnostic representation of a single calendar event."""

    title: str = Field(..., description="Event title / summary.")
    description: Optional[str] = Field(
        None, description="Full event body / notes."
    )
    start_datetime: datetime = Field(
        ..., description="Event start (timezone-aware ISO-8601 string)."
    )
    end_datetime: datetime = Field(
        ..., description="Event end (timezone-aware ISO-8601 string)."
    )
    location: Optional[str] = Field(
        None, description="Physical or virtual location.")
    timezone: str = Field(
        "Europe/Rome",
        description="IANA timezone name.  Used when datetimes are naive.",
    )
    all_day: bool = Field(
        False, description="When True, start/end dates are treated as all-day."
    )
    reminders_minutes_before: list[int] = Field(
        default_factory=lambda: [30],
        description="Popup reminder offsets in minutes before the event.",
    )
    source_reference: Optional[str] = Field(
        None,
        description="Free-text note about where this event was extracted from, "
                    "e.g. 'PDF: medical appointment 2026-04-18'.",
    )


_EVENT_FIELDS = set(CalendarEvent.model_fields)


class CreateEventRequest(BaseModel):
    """Request body for POST /api/calendar/events.

    Also takes the flat shape of the ``create_event`` / ``calendar_create_event`` tools ({title, start_datetime,
    …, provider}): the assistant sends that, and every call was a 422 «event: Field required» (bench with a
    real model, 2026-10-30). No end = one hour after the start."""

    event: CalendarEvent
    target_providers: list[str] = Field(
        default_factory=list,
        description="Provider names to write to.  Empty list means ALL "
                    "configured and available providers.",
    )
    calendar_id: str = Field(
        "primary",
        description="Calendar identifier within the provider.  "
                    "'primary' selects the user's default calendar.",
    )

    @model_validator(mode="before")
    @classmethod
    def _flat_tool_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "event" not in data and "title" in data:
            data["event"] = {k: data.pop(k) for k in list(data) if k in _EVENT_FIELDS}
        provider = data.pop("provider", None)
        if provider and not data.get("target_providers"):
            data["target_providers"] = [provider]
        event = data.get("event")
        if isinstance(event, dict) and event.get("start_datetime") and not event.get("end_datetime"):
            try:
                start = datetime.fromisoformat(str(event["start_datetime"]).replace("Z", "+00:00"))
                data["event"] = {**event, "end_datetime": (start + timedelta(hours=1)).isoformat()}
            except ValueError:
                pass  # the field validator reports the bad start
        return data


class ProviderEventResult(BaseModel):
    """Outcome of a single-provider event creation attempt."""

    provider: str
    success: bool
    event_id: Optional[str] = None
    error: Optional[str] = None


class CreateEventResponse(BaseModel):
    """Response body for POST /api/calendar/events."""

    results: list[ProviderEventResult]
    total_created: int
    total_failed: int


class ListEventsRequest(BaseModel):
    """Request body for POST /api/calendar/events/list."""

    start_datetime: datetime
    end_datetime: datetime
    target_providers: list[str] = Field(default_factory=list)
    calendar_id: str = "primary"
    max_results: int = Field(50, ge=1, le=250)


class CalendarEventRecord(BaseModel):
    """A calendar event as returned by a provider, normalised."""

    provider: str
    event_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    location: Optional[str] = None
    html_link: Optional[str] = None


class ListEventsResponse(BaseModel):
    events: list[CalendarEventRecord]
    provider_errors: dict[str, str] = Field(default_factory=dict)


class DeleteEventRequest(BaseModel):
    """Request body for DELETE /api/calendar/events/{event_id}."""

    provider: str
    calendar_id: str = "primary"


class UpdateEventRequest(BaseModel):
    """Request body for PATCH /api/calendar/events/{event_id}."""

    provider: str
    updates: dict
    calendar_id: str = "primary"

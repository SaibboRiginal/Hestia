"""Calendar event schemas shared across the service."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


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


class CreateEventRequest(BaseModel):
    """Request body for POST /api/calendar/events."""

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

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    title: str = Field(..., description="Event title / summary.")
    description: Optional[str] = Field(None, description="Full event body / notes.")
    start_datetime: datetime = Field(..., description="Event start (timezone-aware ISO-8601 string).")
    end_datetime: datetime = Field(..., description="Event end (timezone-aware ISO-8601 string).")
    location: Optional[str] = Field(None, description="Physical or virtual location.")
    timezone: str = Field("Europe/Rome", description="IANA timezone name.")
    all_day: bool = Field(False, description="When True, start/end dates are treated as all-day.")
    reminders_minutes_before: list[int] = Field(default_factory=lambda: [30])


class CalendarEventRecord(BaseModel):
    provider: str
    event_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    location: Optional[str] = None
    html_link: Optional[str] = None

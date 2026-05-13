from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from schemas.calendar_events import CalendarEvent, CalendarEventRecord


class AbstractCalendarProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> str:
        pass

    @abstractmethod
    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEventRecord]:
        pass

    @abstractmethod
    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        pass

    @abstractmethod
    def update_event(self, event_id: str, updates: dict, calendar_id: str = "primary") -> bool:
        pass

    @abstractmethod
    def refresh(self) -> bool:
        """Re-acquire credentials / access tokens. Returns True if provider is still available after refresh."""
        pass

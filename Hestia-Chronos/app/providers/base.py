"""Abstract base class for all calendar providers.

Every concrete provider (Google, Outlook, …) must implement this interface.
The service layer only ever interacts with this abstraction — adding a new
calendar backend requires no changes outside its own provider module.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from schemas.events import CalendarEvent, CalendarEventRecord


class AbstractCalendarProvider(ABC):
    """Contract that every calendar backend implementation must satisfy."""

    # ─────────────────────────────────────────────────────────────────
    #  Identity
    # ─────────────────────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique lowercase identifier for this provider, e.g. ``"google"``."""

    # ─────────────────────────────────────────────────────────────────
    #  Lifecycle
    # ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the provider is fully configured and reachable.

        Called once at startup; unavailable providers are omitted from the
        active provider list and reported in the health endpoint.
        """

    # ─────────────────────────────────────────────────────────────────
    #  CRUD operations
    # ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def create_event(
        self,
        event: CalendarEvent,
        calendar_id: str = "primary",
    ) -> str:
        """Create a calendar event and return the provider-assigned event ID.

        Raises ``RuntimeError`` on failure so the service layer can collect
        per-provider outcomes without crashing the whole request.
        """

    @abstractmethod
    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEventRecord]:
        """Return events within the given time window, normalised to
        ``CalendarEventRecord``.
        """

    @abstractmethod
    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Delete an event by its provider-issued ID.

        Returns True on success, False if the event was not found.
        Raises ``RuntimeError`` for unexpected errors.
        """

    @abstractmethod
    def update_event(
        self,
        event_id: str,
        updates: dict,
        calendar_id: str = "primary",
    ) -> bool:
        """Partially update an existing event.

        ``updates`` is a dict of field names → new values using the same
        field names as ``CalendarEvent``.  Only supplied fields are changed.
        """

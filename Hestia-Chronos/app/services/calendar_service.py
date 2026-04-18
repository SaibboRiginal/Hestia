"""Calendar service — orchestrates multi-provider event operations.

All business logic lives here; the FastAPI layer is a thin HTTP adapter.
"""
from __future__ import annotations

import logging
from datetime import datetime

from providers.registry import CalendarProviderRegistry
from schemas.events import (
    CalendarEvent,
    CalendarEventRecord,
    CreateEventResponse,
    ListEventsResponse,
    ProviderEventResult,
)

logger = logging.getLogger("hestia_chronos.service")


class CalendarService:
    """Coordinates create / list / delete / update across all active providers."""

    def __init__(self, registry: CalendarProviderRegistry) -> None:
        self._registry = registry

    # ─────────────────────────────────────────────────────────────────
    #  Create
    # ─────────────────────────────────────────────────────────────────

    def create_event(
        self,
        event: CalendarEvent,
        target_providers: list[str],
        calendar_id: str = "primary",
    ) -> CreateEventResponse:
        """Create the event in all target providers simultaneously.

        Provider failures are collected and returned as structured errors
        rather than raising an exception, so that a failure on one backend
        does not prevent creation on the others.
        """
        providers = self._registry.resolve(target_providers)
        if not providers:
            logger.warning(
                "[CREATE] No active providers available for targets=%s", target_providers
            )
            return CreateEventResponse(results=[], total_created=0, total_failed=0)

        results: list[ProviderEventResult] = []
        for provider in providers:
            try:
                event_id = provider.create_event(
                    event, calendar_id=calendar_id)
                results.append(
                    ProviderEventResult(
                        provider=provider.name,
                        success=True,
                        event_id=event_id,
                    )
                )
                logger.info(
                    "[CREATE] %s → event_id=%s title='%s'",
                    provider.name,
                    event_id,
                    event.title,
                )
            except Exception as exc:
                error_msg = str(exc)
                results.append(
                    ProviderEventResult(
                        provider=provider.name,
                        success=False,
                        error=error_msg,
                    )
                )
                logger.error(
                    "[CREATE] %s failed title='%s': %s",
                    provider.name,
                    event.title,
                    error_msg,
                )

        total_created = sum(1 for r in results if r.success)
        total_failed = len(results) - total_created
        return CreateEventResponse(
            results=results,
            total_created=total_created,
            total_failed=total_failed,
        )

    # ─────────────────────────────────────────────────────────────────
    #  List
    # ─────────────────────────────────────────────────────────────────

    def list_events(
        self,
        start: datetime,
        end: datetime,
        target_providers: list[str],
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> ListEventsResponse:
        providers = self._registry.resolve(target_providers)
        all_events: list[CalendarEventRecord] = []
        errors: dict[str, str] = {}

        for provider in providers:
            try:
                events = provider.list_events(
                    start, end, calendar_id=calendar_id, max_results=max_results
                )
                all_events.extend(events)
                logger.info(
                    "[LIST] %s → %d event(s)", provider.name, len(events)
                )
            except Exception as exc:
                errors[provider.name] = str(exc)
                logger.error("[LIST] %s failed: %s", provider.name, exc)

        all_events.sort(
            key=lambda e: e.start_datetime or "",
        )
        return ListEventsResponse(events=all_events, provider_errors=errors)

    # ─────────────────────────────────────────────────────────────────
    #  Delete
    # ─────────────────────────────────────────────────────────────────

    def delete_event(
        self, event_id: str, provider_name: str, calendar_id: str = "primary"
    ) -> dict:
        provider = self._registry.get(provider_name)
        if provider is None:
            return {"success": False, "error": f"Provider '{provider_name}' not available."}
        try:
            found = provider.delete_event(event_id, calendar_id=calendar_id)
            if found:
                logger.info("[DELETE] %s event_id=%s", provider_name, event_id)
            else:
                logger.warning(
                    "[DELETE] %s event_id=%s not found", provider_name, event_id
                )
            return {"success": found, "error": None if found else "Event not found."}
        except Exception as exc:
            logger.error("[DELETE] %s event_id=%s: %s",
                         provider_name, event_id, exc)
            return {"success": False, "error": str(exc)}

    # ─────────────────────────────────────────────────────────────────
    #  Update
    # ─────────────────────────────────────────────────────────────────

    def update_event(
        self,
        event_id: str,
        provider_name: str,
        updates: dict,
        calendar_id: str = "primary",
    ) -> dict:
        provider = self._registry.get(provider_name)
        if provider is None:
            return {"success": False, "error": f"Provider '{provider_name}' not available."}
        try:
            provider.update_event(event_id, updates, calendar_id=calendar_id)
            logger.info(
                "[UPDATE] %s event_id=%s fields=%s",
                provider_name,
                event_id,
                list(updates.keys()),
            )
            return {"success": True, "error": None}
        except Exception as exc:
            logger.error("[UPDATE] %s event_id=%s: %s",
                         provider_name, event_id, exc)
            return {"success": False, "error": str(exc)}

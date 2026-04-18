"""Provider registry — discovers and holds all configured calendar providers.

At startup, the registry instantiates every known provider.  Only those
whose ``is_available()`` returns True are placed in the active pool.
Adding a new provider requires only importing its class here and appending
it to ``_KNOWN_PROVIDERS``.
"""
from __future__ import annotations

import logging
from typing import Optional

from providers.base import AbstractCalendarProvider
from providers.google import GoogleCalendarProvider
from providers.outlook import OutlookCalendarProvider

logger = logging.getLogger("hestia_chronos.registry")

# ─────────────────────────────────────────────────────────────────────
#  Registration table — add new provider classes here only
# ─────────────────────────────────────────────────────────────────────
_KNOWN_PROVIDER_CLASSES: list[type[AbstractCalendarProvider]] = [
    GoogleCalendarProvider,
    OutlookCalendarProvider,
]


class CalendarProviderRegistry:
    """Holds all active (configured + reachable) calendar providers."""

    def __init__(self) -> None:
        self._active: dict[str, AbstractCalendarProvider] = {}
        self._unavailable: dict[str, str] = {}
        self._load()

    # ─────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────

    @property
    def active_providers(self) -> list[AbstractCalendarProvider]:
        return list(self._active.values())

    @property
    def active_names(self) -> list[str]:
        return list(self._active.keys())

    @property
    def unavailable(self) -> dict[str, str]:
        """Maps provider name → init error message for unavailable providers."""
        return dict(self._unavailable)

    def get(self, name: str) -> Optional[AbstractCalendarProvider]:
        """Return an active provider by name, or None if unknown/unavailable."""
        return self._active.get(name)

    def resolve(self, requested: list[str]) -> list[AbstractCalendarProvider]:
        """Return the providers that should handle a request.

        If ``requested`` is empty, returns **all** active providers.
        Unknown or unavailable names are silently skipped (the caller
        receives the provider-level error in the response).
        """
        if not requested:
            return self.active_providers
        return [p for name in requested if (p := self._active.get(name))]

    def status_report(self) -> dict:
        return {
            "active": self.active_names,
            "unavailable": self._unavailable,
        }

    # ─────────────────────────────────────────────────────────────────
    #  Internal
    # ─────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        for cls in _KNOWN_PROVIDER_CLASSES:
            try:
                instance = cls()
                if instance.is_available():
                    self._active[instance.name] = instance
                    logger.info(
                        "[REGISTRY] Provider '%s' is active.", instance.name)
                else:
                    # Collect the init error if the provider exposes one
                    error_msg = getattr(
                        instance, "_init_error", "not configured")
                    self._unavailable[instance.name] = error_msg or "not available"
                    logger.warning(
                        "[REGISTRY] Provider '%s' is unavailable: %s",
                        instance.name,
                        error_msg,
                    )
            except Exception as exc:
                name = getattr(cls, "__name__", str(cls))
                self._unavailable[name] = str(exc)
                logger.error(
                    "[REGISTRY] Failed to instantiate provider %s: %s", name, exc)

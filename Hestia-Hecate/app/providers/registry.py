from __future__ import annotations

import logging
from typing import Optional

from providers.base import AbstractCalendarProvider
from providers.google import GoogleCalendarProvider
from providers.outlook import OutlookCalendarProvider

logger = logging.getLogger("hestia_hecate.registry")

_KNOWN_PROVIDER_CLASSES: list[type[AbstractCalendarProvider]] = [
    GoogleCalendarProvider,
    OutlookCalendarProvider,
]


class CalendarProviderRegistry:
    def __init__(self) -> None:
        self._active: dict[str, AbstractCalendarProvider] = {}
        self._unavailable: dict[str, str] = {}
        self._load()

    @property
    def active_providers(self) -> list[AbstractCalendarProvider]:
        return list(self._active.values())

    @property
    def active_names(self) -> list[str]:
        return list(self._active.keys())

    @property
    def unavailable(self) -> dict[str, str]:
        return dict(self._unavailable)

    def get(self, name: str) -> Optional[AbstractCalendarProvider]:
        return self._active.get(name)

    def resolve(self, requested: list[str]) -> list[AbstractCalendarProvider]:
        if not requested:
            return self.active_providers
        return [p for name in requested if (p := self._active.get(name))]

    def status_report(self) -> dict:
        return {"active": self.active_names, "unavailable": self._unavailable}

    def _load(self) -> None:
        for cls in _KNOWN_PROVIDER_CLASSES:
            try:
                instance = cls()
                if instance.is_available():
                    self._active[instance.name] = instance
                    logger.info("event=provider_active Provider '%s' active", instance.name)
                else:
                    msg = getattr(instance, "_init_error", "not configured") or "not configured"
                    self._unavailable[instance.name] = msg
                    logger.info("event=provider_unavailable Provider '%s' unavailable: %s", instance.name, msg)
            except Exception as exc:
                name = getattr(cls, "__name__", str(cls))
                self._unavailable[name] = str(exc)
                logger.warning("event=provider_init_failed Provider '%s' init failed: %s", name, exc)

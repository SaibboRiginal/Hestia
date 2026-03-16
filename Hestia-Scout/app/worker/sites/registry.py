"""Registry that resolves the appropriate site handler for a listing URL."""

from typing import Optional

from worker.sites.base import BaseSiteHandler
from worker.sites.idealista import IdealistaSiteHandler
from worker.sites.immobiliare import ImmobiliareSiteHandler


class SiteHandlerRegistry:
    """Maintains an ordered list of site handlers and resolves by URL."""

    def __init__(self) -> None:
        self._handlers: list[BaseSiteHandler] = [
            IdealistaSiteHandler(),
            ImmobiliareSiteHandler(),
        ]

    def get_handler(self, url: str) -> Optional[BaseSiteHandler]:
        """Return the first handler that can process *url*, or ``None``."""
        for handler in self._handlers:
            if handler.can_handle(url):
                return handler
        return None

    def register(self, handler: BaseSiteHandler) -> None:
        """Add a new handler to the registry."""
        self._handlers.append(handler)

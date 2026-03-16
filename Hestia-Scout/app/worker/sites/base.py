"""Abstract base for website-specific listing enrichment.

Each real-estate portal has its own HTML structure. Subclasses implement
site-specific logic for extracting structured data from a listing page.

The LLM handles primary extraction from notification emails; site handlers
augment and verify that data by parsing the actual listing page.
"""

from abc import ABC, abstractmethod

from bs4 import BeautifulSoup


class BaseSiteHandler(ABC):
    """Handles listing enrichment for a specific real-estate website."""

    @property
    @abstractmethod
    def site_name(self) -> str:
        """Human-readable site identifier (e.g. ``'idealista'``)."""

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return ``True`` if this handler supports the given URL."""

    @abstractmethod
    def enrich(self, soup: BeautifulSoup, payload: dict) -> dict:
        """Enrich *payload* with data extracted from the listing page.

        Args:
            soup: Parsed HTML of the listing page.
            payload: Current entity payload (from LLM + prior enrichment).

        Returns:
            Updated payload dict with any new or improved fields.
        """

    def normalize_url(self, url: str) -> str:
        """Normalize URL for a consistent ``entity_id``.  Override per site."""
        return url.strip()

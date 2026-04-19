"""Outlook Calendar fetcher for Hestia-Ingest.

Calls Chronos's ``POST /api/calendar/events/list`` endpoint (filtered to the
Outlook provider) and returns normalised dicts suitable for archiving as
CalendarItems.  All credential management stays in Chronos — Ingest only
needs the Chronos URL.

The ``custom_filter`` argument is used as the ``calendar_id`` (default
"primary").  For Outlook this can be a specific calendar folder id.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from core.base_fetcher import BaseFetcher

logger = logging.getLogger("hestia_ingest.outlook_fetcher")

_CHRONOS_URL = os.getenv("CHRONOS_URL", "http://hestia_chronos:19007")
_TIMEOUT = 20


class OutlookFetcher(BaseFetcher):
    """Fetch Outlook calendar events via the Chronos /api/calendar/events/list proxy."""

    def __init__(self) -> None:
        self._chronos_url = _CHRONOS_URL.rstrip("/")

    # ── BaseFetcher interface ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Verify Chronos is reachable."""
        try:
            resp = requests.get(f"{self._chronos_url}/health", timeout=5)
            if resp.status_code < 300:
                return True
            logger.warning(
                "[OUTLOOK] Chronos health check failed status=%s", resp.status_code)
        except Exception as exc:
            logger.warning("[OUTLOOK] Cannot reach Chronos: %s", exc)
        return False

    def fetch_new_data(self, since_date: datetime, custom_filter: str = "primary") -> list[dict[str, Any]]:
        """Fetch Outlook calendar events from ``since_date`` up to 90 days ahead.

        ``custom_filter`` is used as the ``calendar_id`` (e.g. "primary" or a
        specific Outlook calendar folder id).
        """
        calendar_id = custom_filter.strip(
        ) if custom_filter and custom_filter.strip() else "primary"
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=90)
        start = max(since_date.replace(tzinfo=timezone.utc)
                    if since_date.tzinfo is None else since_date, now)

        payload = {
            "start_datetime": start.isoformat(),
            "end_datetime": end.isoformat(),
            "target_providers": ["outlook"],
            "calendar_id": calendar_id,
            "max_results": 250,
        }

        try:
            resp = requests.post(
                f"{self._chronos_url}/api/calendar/events/list",
                json=payload,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.error("[OUTLOOK] list_events call failed: %s", exc)
            return []

        data = resp.json()
        events: list[dict] = data.get("events", [])
        return [_normalise(e, "outlook") for e in events]

    def disconnect(self) -> None:
        pass  # Stateless HTTP fetcher


# ─────────────────────────────────────────────────────────────────────────────


def _normalise(event: dict, source: str) -> dict[str, Any]:
    """Map a CalendarEventRecord (from Chronos) to a CalendarItemCreate-compatible dict."""
    return {
        "external_id": event.get("event_id"),
        "source": source,
        "kind": "event",
        "title": event.get("title") or "Untitled",
        "description": event.get("description"),
        "start_at": event.get("start_datetime"),
        "end_at": event.get("end_datetime"),
        "all_day": False,
        "location": event.get("location"),
        "attendees": [],
        "recurrence": None,
        "status": "confirmed",
        "html_link": event.get("html_link"),
        "nag_enabled": True,
    }

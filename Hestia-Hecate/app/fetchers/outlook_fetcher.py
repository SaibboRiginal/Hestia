"""Outlook Calendar fetcher for Hestia-Hecate.

Calls Hecate through Hub routing using ``/route/hecate/api/gateway/calendar/events``
and returns normalised dicts suitable for archiving as CalendarItems.

The ``custom_filter`` argument is used as the ``calendar_id`` (default
"primary").
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from core.base_fetcher import BaseFetcher

logger = logging.getLogger("hestia_hecate.outlook_fetcher")

_TIMEOUT = 20


class OutlookFetcher(BaseFetcher):
    """Fetch Outlook calendar events via Hub-routed Hecate calls."""

    def __init__(self) -> None:
        self._hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

    # ── BaseFetcher interface ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Verify Hub is reachable for routed Hecate requests."""
        try:
            resp = requests.get(
                f"{self._hub_api_url}/registry/services", timeout=5)
            if resp.status_code < 300:
                return True
            logger.warning(
                "event=outlook_hub_health_check_failed [OUTLOOK] Hub health check failed status=%s", resp.status_code)
        except Exception as exc:
            logger.warning(
                "event=outlook_cannot_reach_hub [OUTLOOK] Cannot reach Hub: %s", exc)
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

        query = {
            "start_datetime": start.isoformat(),
            "end_datetime": end.isoformat(),
            "provider": "outlook",
            "calendar_id": calendar_id,
            "max_results": 250,
        }

        envelope = {
            "method": "GET",
            "headers": {},
            "query": query,
            "body": None,
            "timeout_seconds": _TIMEOUT,
        }
        try:
            resp = requests.post(
                f"{self._hub_api_url}/route/hecate/api/gateway/calendar/events",
                json=envelope,
                timeout=_TIMEOUT + 2,
            )
            resp.raise_for_status()
            routed = resp.json() if resp.content else {}
            if int((routed or {}).get("status_code", 500)) >= 400:
                return []
            data = (routed or {}).get("payload") or {}
        except Exception as exc:
            logger.error(
                "event=outlook_list_events_call_failed [OUTLOOK] list_events call failed: %s", exc)
            return []

        events: list[dict] = data.get("events", [])
        return [_normalise(e, "outlook") for e in events]

    def disconnect(self) -> None:
        pass  # Stateless HTTP fetcher


# ─────────────────────────────────────────────────────────────────────────────


def _normalise(event: dict, source: str) -> dict[str, Any]:
    """Map a gateway calendar event payload to a CalendarItemCreate-compatible dict."""
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

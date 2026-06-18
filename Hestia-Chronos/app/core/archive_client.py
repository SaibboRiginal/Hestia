"""Archive client — thin HTTP wrapper used by Chronos to sync calendar items.

Chronos is the authoritative writer for calendar events created / updated /
deleted through its own API.  After each mutation it calls Archive to keep
the persistent calendar-item store up to date so that:

  * The Chronos notification worker can query upcoming events without
    needing to contact each calendar provider at notification time.
  * Oracle and other services can read the assistant's full calendar
    context directly from Archive.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger("hestia_chronos.archive_client")

_HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
_TIMEOUT = 8


def _route_archive(method: str, endpoint: str, body=None, query=None, timeout: int = 8):
    """Route a request to Archive through Hub."""
    try:
        resp = requests.post(
            f"{_HUB_API_URL}/route/archive/{endpoint.lstrip('/')}",
            json={
                "method": method.upper(),
                "headers": {},
                "query": query or {},
                "body": body,
                "timeout_seconds": timeout,
            },
            timeout=timeout + 1,
        )
        if resp.status_code != 200:
            return None
        routed = resp.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            return None
        return routed.get("payload")
    except Exception as exc:
        logger.warning(
            "event=archive_route_error endpoint=%s error=%s", endpoint, exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Write helpers
# ─────────────────────────────────────────────────────────────────────────────


def upsert_calendar_item(
    *,
    external_id: Optional[str],
    source: str,
    kind: str = "event",
    title: str,
    description: Optional[str] = None,
    start_at: str,
    end_at: Optional[str] = None,
    all_day: bool = False,
    location: Optional[str] = None,
    attendees: Optional[list[dict[str, Any]]] = None,
    recurrence: Optional[str] = None,
    status: str = "confirmed",
    html_link: Optional[str] = None,
    nag_enabled: bool = True,
) -> Optional[dict]:
    """Upsert a calendar event / task / reminder into Archive.

    Returns the saved CalendarItemRead dict on success, or None on failure.
    Failures are logged as warnings — they must not propagate to the caller
    so that a transient Archive outage never blocks calendar CRUD operations.
    """
    payload: dict[str, Any] = {
        "external_id": external_id,
        "source": source,
        "kind": kind,
        "title": title,
        "description": description,
        "start_at": start_at,
        "end_at": end_at,
        "all_day": all_day,
        "location": location,
        "attendees": attendees or [],
        "recurrence": recurrence,
        "status": status,
        "html_link": html_link,
        "nag_enabled": nag_enabled,
    }
    try:
        result = _route_archive(
            "POST", "api/calendar/items", body=payload, timeout=_TIMEOUT)
        if result is not None:
            return result if isinstance(result, dict) else None
        logger.warning(
            "event=archive_upsert_calendar_item_failed [ARCHIVE] upsert_calendar_item failed"
        )
    except Exception as exc:
        logger.warning("event=archive_upsert_calendar_item_error [ARCHIVE] upsert_calendar_item error: %s", exc)
    return None


def delete_calendar_item_by_external(source: str, external_id: str) -> bool:
    """Remove a calendar item from Archive after it has been deleted from its provider."""
    try:
        result = _route_archive(
            "DELETE",
            f"api/calendar/items/by-external/{source}/{external_id}",
            timeout=_TIMEOUT,
        )
        return result is not None
    except Exception as exc:
        logger.warning("event=archive_delete_calendar_item_error [ARCHIVE] delete_calendar_item error: %s", exc)
        return False


def mark_notified(item_id: int, bucket: str) -> bool:
    """Update last_notified_bucket for a CalendarItem (called by notification worker)."""
    try:
        result = _route_archive(
            "PATCH",
            f"api/calendar/items/{item_id}/notified",
            body={"last_notified_bucket": bucket},
            timeout=_TIMEOUT,
        )
        return result is not None
    except Exception as exc:
        logger.warning("event=archive_mark_notified_error [ARCHIVE] mark_notified error: %s", exc)
        return False


def set_nag(item_id: int, enabled: bool) -> bool:
    """Toggle nag for a specific calendar item."""
    try:
        result = _route_archive(
            "PATCH",
            f"api/calendar/items/{item_id}/nag",
            body={"nag_enabled": enabled},
            timeout=_TIMEOUT,
        )
        return result is not None
    except Exception as exc:
        logger.warning("event=archive_set_nag_error [ARCHIVE] set_nag error: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Read helpers
# ─────────────────────────────────────────────────────────────────────────────


def list_upcoming(
    from_time: str,
    to_time: str,
    nag_enabled: Optional[bool] = None,
    limit: int = 200,
) -> list[dict]:
    """Return calendar items whose start_at falls in [from_time, to_time].

    Used by the notification worker to discover events that need reminders.
    """
    query: dict[str, Any] = {
        "from_time": from_time,
        "to_time": to_time,
        "status_filter": "confirmed",
        "limit": limit,
    }
    if nag_enabled is not None:
        query["nag_enabled"] = str(nag_enabled).lower()
    try:
        result = _route_archive(
            "GET", "api/calendar/items", query=query, timeout=_TIMEOUT)
        if isinstance(result, list):
            return result
        logger.warning(
            "event=archive_list_upcoming_failed [ARCHIVE] list_upcoming failed"
        )
    except Exception as exc:
        logger.warning("event=archive_list_upcoming_error [ARCHIVE] list_upcoming error: %s", exc)
    return []


def list_items(
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    source: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """General calendar item listing used by the agenda endpoint."""
    query: dict[str, Any] = {"limit": limit}
    if from_time:
        query["from_time"] = from_time
    if to_time:
        query["to_time"] = to_time
    if source:
        query["source"] = source
    if kind:
        query["kind"] = kind
    try:
        result = _route_archive(
            "GET", "api/calendar/items", query=query, timeout=_TIMEOUT)
        if isinstance(result, list):
            return result
        logger.warning(
            "event=archive_list_items_failed [ARCHIVE] list_items failed")
    except Exception as exc:
        logger.warning("event=archive_list_items_error [ARCHIVE] list_items error: %s", exc)
    return []

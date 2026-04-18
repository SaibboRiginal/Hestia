"""Microsoft Outlook / Office 365 calendar provider.

Uses the Microsoft Graph API (https://graph.microsoft.com/v1.0) with
MSAL for authentication.

Supported authentication modes:
1. **Client credentials** (application permissions, for organizational accounts):
   Set ``OUTLOOK_CLIENT_ID``, ``OUTLOOK_CLIENT_SECRET``, ``OUTLOOK_TENANT_ID``.
   The user's UPN must also be set via ``OUTLOOK_USER_ID`` (e.g. user@domain.com).

2. **Device code / user token** (delegated permissions, for personal accounts):
   Set ``OUTLOOK_CLIENT_ID``, ``OUTLOOK_TENANT_ID="consumers"``, and
   ``OUTLOOK_REFRESH_TOKEN`` (obtained by running the one-time helper script
   ``scripts/outlook_oauth_setup.py`` on the host).

The ``OUTLOOK_USER_ID`` env var selects whose calendar is managed.  Use
``"me"`` for the authenticated user (delegated flow) or the full UPN for
application flow.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from providers.base import AbstractCalendarProvider
from schemas.events import CalendarEvent, CalendarEventRecord

logger = logging.getLogger("hestia_chronos.outlook")

try:
    import msal
    import requests as _requests

    _OUTLOOK_LIBS_AVAILABLE = True
except ImportError:
    _OUTLOOK_LIBS_AVAILABLE = False


_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE_CALENDAR = ["https://graph.microsoft.com/Calendars.ReadWrite"]


class OutlookCalendarProvider(AbstractCalendarProvider):
    """Microsoft Outlook / Office 365 CRUD via Microsoft Graph API."""

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._user_id: str = os.getenv("OUTLOOK_USER_ID", "me")
        self._init_error: Optional[str] = None
        self._setup()

    # ─────────────────────────────────────────────────────────────────
    #  AbstractCalendarProvider interface
    # ─────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "outlook"

    def is_available(self) -> bool:
        return self._token is not None

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> str:
        url = self._events_url(calendar_id)
        body = _build_outlook_event_body(event)
        resp = self._post(url, body)
        event_id: str = resp.get("id", "")
        logger.info("[OUTLOOK] Created event id=%s title=%s",
                    event_id, event.title)
        return event_id

    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEventRecord]:
        url = self._events_url(calendar_id)
        params = {
            "$select": "id,subject,body,start,end,location,webLink",
            "$filter": (
                f"start/dateTime ge '{_to_iso(start)}' "
                f"and end/dateTime le '{_to_iso(end)}'"
            ),
            "$top": str(max_results),
            "$orderby": "start/dateTime asc",
        }
        resp = self._get(url, params=params)
        items = resp.get("value", [])
        return [_outlook_item_to_record(item) for item in items]

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        url = f"{self._events_url(calendar_id)}/{event_id}"
        try:
            resp = _requests.delete(
                url, headers=self._auth_headers(), timeout=10)
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            logger.info("[OUTLOOK] Deleted event id=%s", event_id)
            return True
        except Exception as exc:
            raise RuntimeError(f"Outlook delete failed: {exc}") from exc

    def update_event(
        self, event_id: str, updates: dict, calendar_id: str = "primary"
    ) -> bool:
        url = f"{self._events_url(calendar_id)}/{event_id}"
        patch = _build_outlook_patch_body(updates)
        resp = _requests.patch(
            url, json=patch, headers=self._auth_headers(), timeout=10
        )
        resp.raise_for_status()
        logger.info("[OUTLOOK] Updated event id=%s fields=%s",
                    event_id, list(updates.keys()))
        return True

    # ─────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ─────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        if not _OUTLOOK_LIBS_AVAILABLE:
            self._init_error = "msal and requests not installed"
            logger.warning("[OUTLOOK] %s", self._init_error)
            return

        client_id = os.getenv("OUTLOOK_CLIENT_ID", "").strip()
        tenant_id = os.getenv("OUTLOOK_TENANT_ID", "").strip()

        if not client_id or not tenant_id:
            self._init_error = (
                "OUTLOOK_CLIENT_ID and OUTLOOK_TENANT_ID must be set."
            )
            logger.warning("[OUTLOOK] %s", self._init_error)
            return

        # Try delegated flow first (refresh token)
        refresh_token = os.getenv("OUTLOOK_REFRESH_TOKEN", "").strip()
        client_secret = os.getenv("OUTLOOK_CLIENT_SECRET", "").strip()

        if refresh_token:
            self._token = self._acquire_token_by_refresh(
                client_id, tenant_id, client_secret, refresh_token
            )
        elif client_secret:
            self._token = self._acquire_token_client_credentials(
                client_id, tenant_id, client_secret
            )
        else:
            self._init_error = (
                "Provide OUTLOOK_REFRESH_TOKEN (personal/delegated) or "
                "OUTLOOK_CLIENT_SECRET (application flow)."
            )
            logger.warning("[OUTLOOK] %s", self._init_error)

    def _acquire_token_by_refresh(
        self, client_id: str, tenant_id: str, client_secret: str, refresh_token: str
    ) -> Optional[str]:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.PublicClientApplication(client_id, authority=authority)
        result = app.acquire_token_by_refresh_token(
            refresh_token, scopes=_SCOPE_CALENDAR
        )
        if "access_token" in result:
            logger.info("[OUTLOOK] Token acquired via refresh token.")
            return result["access_token"]
        self._init_error = f"Token refresh failed: {result.get('error_description')}"
        logger.error("[OUTLOOK] %s", self._init_error)
        return None

    def _acquire_token_client_credentials(
        self, client_id: str, tenant_id: str, client_secret: str
    ) -> Optional[str]:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id, authority=authority, client_credential=client_secret
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" in result:
            logger.info("[OUTLOOK] Token acquired via client credentials.")
            return result["access_token"]
        self._init_error = f"Client credentials failed: {result.get('error_description')}"
        logger.error("[OUTLOOK] %s", self._init_error)
        return None

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _events_url(self, calendar_id: str) -> str:
        user = self._user_id
        if calendar_id == "primary" or not calendar_id:
            return f"{_GRAPH_BASE}/users/{user}/calendar/events"
        return f"{_GRAPH_BASE}/users/{user}/calendars/{calendar_id}/events"

    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = _requests.get(
            url, headers=self._auth_headers(), params=params, timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, body: dict) -> dict:
        resp = _requests.post(
            url, json=body, headers=self._auth_headers(), timeout=10
        )
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_outlook_event_body(event: CalendarEvent) -> dict:
    body: dict = {
        "subject": event.title,
        "start": {
            "dateTime": _to_iso(event.start_datetime),
            "timeZone": event.timezone,
        },
        "end": {
            "dateTime": _to_iso(event.end_datetime),
            "timeZone": event.timezone,
        },
    }

    if event.description:
        body["body"] = {"contentType": "text", "content": event.description}
    if event.location:
        body["location"] = {"displayName": event.location}
    if event.reminders_minutes_before:
        body["isReminderOn"] = True
        body["reminderMinutesBeforeStart"] = event.reminders_minutes_before[0]

    return body


def _build_outlook_patch_body(updates: dict) -> dict:
    patch: dict = {}
    if "title" in updates:
        patch["subject"] = updates["title"]
    if "description" in updates:
        patch["body"] = {"contentType": "text",
                         "content": updates["description"]}
    if "location" in updates:
        patch["location"] = {"displayName": updates["location"]}
    if "start_datetime" in updates:
        patch["start"] = {
            "dateTime": updates["start_datetime"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "end_datetime" in updates:
        patch["end"] = {
            "dateTime": updates["end_datetime"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    return patch


def _outlook_item_to_record(item: dict) -> CalendarEventRecord:
    start = item.get("start", {})
    end = item.get("end", {})
    body = item.get("body", {})
    loc = item.get("location", {})
    return CalendarEventRecord(
        provider="outlook",
        event_id=item.get("id", ""),
        title=item.get("subject"),
        description=body.get("content") if isinstance(body, dict) else None,
        start_datetime=start.get("dateTime"),
        end_datetime=end.get("dateTime"),
        location=loc.get("displayName") if isinstance(loc, dict) else None,
        html_link=item.get("webLink"),
    )

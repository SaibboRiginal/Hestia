"""Google Calendar provider.

Uses the official Google API Python client library with OAuth2 credentials.

Supported credential modes (in priority order):
1. Service account JSON via ``GOOGLE_SERVICE_ACCOUNT_JSON`` env var
   (full JSON content as a single string).
   Suitable for G-Suite / Workspace accounts with domain-wide delegation.
2. User OAuth token JSON via ``GOOGLE_TOKEN_JSON`` env var
   (the token.json produced by the OAuth2 flow, serialised as a string).
   Suitable for personal Google accounts.

To obtain a user OAuth token, run the one-time helper script
``scripts/google_oauth_setup.py`` on the host (not inside Docker) and copy
the resulting ``token.json`` content into the environment variable.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from providers.base import AbstractCalendarProvider
from schemas.events import CalendarEvent, CalendarEventRecord

logger = logging.getLogger("hestia_chronos.google")

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    _GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    _GOOGLE_LIBS_AVAILABLE = False


_SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarProvider(AbstractCalendarProvider):
    """Google Calendar CRUD via the Google Calendar API v3."""

    def __init__(self) -> None:
        self._service = None
        self._init_error: Optional[str] = None
        self._setup()

    # ─────────────────────────────────────────────────────────────────
    #  AbstractCalendarProvider interface
    # ─────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "google"

    def is_available(self) -> bool:
        return self._service is not None

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> str:
        body = _build_google_event_body(event)
        result = (
            self._service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        event_id: str = result.get("id", "")
        logger.info("event=google_created_event_id_title [GOOGLE] Created event id=%s title=%s",
                    event_id, event.title)
        return event_id

    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEventRecord]:
        time_min = _to_rfc3339(start)
        time_max = _to_rfc3339(end)
        response = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = response.get("items", [])
        return [_google_item_to_record(item) for item in items]

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        try:
            self._service.events().delete(
                calendarId=calendar_id, eventId=event_id
            ).execute()
            logger.info("event=google_deleted_event_id [GOOGLE] Deleted event id=%s", event_id)
            return True
        except Exception as exc:
            if "404" in str(exc):
                return False
            raise RuntimeError(f"Google delete failed: {exc}") from exc

    def update_event(
        self, event_id: str, updates: dict, calendar_id: str = "primary"
    ) -> bool:
        existing = (
            self._service.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute()
        )
        patch = _build_google_patch_body(updates, existing)
        self._service.events().patch(
            calendarId=calendar_id, eventId=event_id, body=patch
        ).execute()
        logger.info("event=google_updated_event_id_fields [GOOGLE] Updated event id=%s fields=%s",
                    event_id, list(updates.keys()))
        return True

    # ─────────────────────────────────────────────────────────────────
    #  Setup
    # ─────────────────────────────────────────────────────────────────

    def _setup(self) -> None:
        if not _GOOGLE_LIBS_AVAILABLE:
            self._init_error = "google-api-python-client not installed"
            logger.warning("event=google [GOOGLE] %s", self._init_error)
            return

        creds = self._load_credentials()
        if creds is None:
            return

        try:
            self._service = build(
                "calendar", "v3", credentials=creds, cache_discovery=False)
            logger.info("event=google_calendar_service_initialised_successfully [GOOGLE] Calendar service initialised successfully.")
        except Exception as exc:
            self._init_error = str(exc)
            logger.error("event=google_failed_build_service [GOOGLE] Failed to build service: %s", exc)

    def _load_credentials(self):
        # Priority 1: service account
        sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if sa_json:
            try:
                info = json.loads(sa_json)
                return service_account.Credentials.from_service_account_info(
                    info, scopes=_SCOPES
                )
            except Exception as exc:
                self._init_error = f"Service account parse error: {exc}"
                logger.error("event=google [GOOGLE] %s", self._init_error)
                return None

        # Priority 2: user OAuth token
        token_json = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
        if token_json:
            try:
                token_data = json.loads(token_json)
                creds = Credentials.from_authorized_user_info(
                    token_data, _SCOPES)
                if creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    logger.info("event=google_oauth_token_refreshed [GOOGLE] OAuth token refreshed.")
                return creds
            except Exception as exc:
                self._init_error = f"OAuth token parse/refresh error: {exc}"
                logger.error("event=google [GOOGLE] %s", self._init_error)
                return None

        self._init_error = (
            "No Google credentials configured. "
            "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_TOKEN_JSON."
        )
        logger.warning("event=google [GOOGLE] %s", self._init_error)
        return None


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_google_event_body(event: CalendarEvent) -> dict:
    body: dict = {
        "summary": event.title,
        "start": {},
        "end": {},
    }

    if event.description:
        body["description"] = event.description
    if event.location:
        body["location"] = event.location

    if event.all_day:
        body["start"] = {"date": event.start_datetime.date().isoformat()}
        body["end"] = {"date": event.end_datetime.date().isoformat()}
    else:
        tz = event.timezone
        body["start"] = {"dateTime": _to_rfc3339(
            event.start_datetime), "timeZone": tz}
        body["end"] = {"dateTime": _to_rfc3339(
            event.end_datetime), "timeZone": tz}

    if event.reminders_minutes_before:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": m}
                for m in event.reminders_minutes_before
            ],
        }
    else:
        body["reminders"] = {"useDefault": True}

    return body


def _build_google_patch_body(updates: dict, existing: dict) -> dict:
    patch: dict = {}
    if "title" in updates:
        patch["summary"] = updates["title"]
    if "description" in updates:
        patch["description"] = updates["description"]
    if "location" in updates:
        patch["location"] = updates["location"]
    if "start_datetime" in updates:
        tz = updates.get("timezone", existing.get(
            "start", {}).get("timeZone", "UTC"))
        patch["start"] = {
            "dateTime": updates["start_datetime"], "timeZone": tz}
    if "end_datetime" in updates:
        tz = updates.get("timezone", existing.get(
            "end", {}).get("timeZone", "UTC"))
        patch["end"] = {"dateTime": updates["end_datetime"], "timeZone": tz}
    return patch


def _google_item_to_record(item: dict) -> CalendarEventRecord:
    start = item.get("start", {})
    end = item.get("end", {})
    return CalendarEventRecord(
        provider="google",
        event_id=item.get("id", ""),
        title=item.get("summary"),
        description=item.get("description"),
        start_datetime=start.get("dateTime") or start.get("date"),
        end_datetime=end.get("dateTime") or end.get("date"),
        location=item.get("location"),
        html_link=item.get("htmlLink"),
    )

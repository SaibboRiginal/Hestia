"""Outlook calendar (Microsoft Graph). The app is the one typed in the «Outlook» card (Connections):
``HECATE_KEY_OUTLOOK_CLIENT_ID``, ``HECATE_KEY_OUTLOOK_TENANT`` (default ``common``), optional
``HECATE_KEY_OUTLOOK_CLIENT_SECRET`` in Hecate's .env; the refresh token the sign-in gives is kept in
``data/outlook_token.json`` (owner-only), so it survives restarts, and is replaced when Microsoft rotates it."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from providers.base import AbstractCalendarProvider
from schemas.calendar_events import CalendarEvent, CalendarEventRecord

logger = logging.getLogger("hestia_hecate.outlook")

try:
    import msal
    import requests as _requests

    _OUTLOOK_LIBS_AVAILABLE = True
except ImportError:
    _OUTLOOK_LIBS_AVAILABLE = False


_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPE_CALENDAR = ["https://graph.microsoft.com/Calendars.ReadWrite"]


def client() -> tuple[str, str, str]:
    """(client id, tenant, client secret) typed in the card."""
    return (os.getenv("HECATE_KEY_OUTLOOK_CLIENT_ID", "").strip(),
            os.getenv("HECATE_KEY_OUTLOOK_TENANT", "").strip() or "common",
            os.getenv("HECATE_KEY_OUTLOOK_CLIENT_SECRET", "").strip())


def token_file() -> Path:
    token = Path(os.getenv("GOOGLE_TOKEN_FILE", "/code/data/google_token.json"))
    return token.parent / "outlook_token.json"


def load_refresh_token() -> str:
    try:
        return str(json.loads(token_file().read_text(encoding="utf-8")).get("refresh_token") or "").strip()
    except (OSError, ValueError):
        return ""


def save_refresh_token(token: str) -> None:
    path = token_file()
    if not token:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"refresh_token": token}), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    logger.info("event=outlook_token_saved")


class OutlookCalendarProvider(AbstractCalendarProvider):
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._user_id: str = "me"
        self._init_error: Optional[str] = None
        self._setup()

    @property
    def name(self) -> str:
        return "outlook"

    def is_available(self) -> bool:
        return self._token is not None

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> str:
        resp = self._post(self._events_url(calendar_id),
                          _build_outlook_event_body(event))
        return str(resp.get("id", ""))

    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEventRecord]:
        params = {
            "$select": "id,subject,body,start,end,location,webLink",
            "$filter": f"start/dateTime ge '{_to_iso(start)}' and end/dateTime le '{_to_iso(end)}'",
            "$top": str(max_results),
            "$orderby": "start/dateTime asc",
        }
        payload = self._get(self._events_url(calendar_id), params=params)
        return [_outlook_item_to_record(item) for item in payload.get("value", [])]

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        url = f"{self._events_url(calendar_id)}/{event_id}"
        try:
            resp = _requests.delete(
                url, headers=self._auth_headers(), timeout=10)
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            return True
        except Exception as exc:
            raise RuntimeError(f"Outlook delete failed: {exc}") from exc

    def update_event(self, event_id: str, updates: dict, calendar_id: str = "primary") -> bool:
        url = f"{self._events_url(calendar_id)}/{event_id}"
        patch = _build_outlook_patch_body(updates)
        resp = _requests.patch(
            url, json=patch, headers=self._auth_headers(), timeout=10)
        resp.raise_for_status()
        return True

    def refresh(self) -> bool:
        """Re-acquire the Outlook access token. Returns True if provider is still available after refresh."""
        logger.info("event=outlook_provider_refresh Refreshing Outlook token")
        self._token = None
        self._init_error = None
        self._setup()
        available = self.is_available()
        logger.info("event=outlook_provider_refresh_result available=%s error=%s",
                    available, self._init_error)
        return available

    def _setup(self) -> None:
        if not _OUTLOOK_LIBS_AVAILABLE:
            self._init_error = "msal and requests not installed"
            return

        client_id, tenant_id, client_secret = client()
        if not client_id:
            self._init_error = "Outlook not linked."
            return

        refresh_token = load_refresh_token()

        if refresh_token:
            self._token = self._acquire_token_by_refresh(
                client_id, tenant_id, client_secret, refresh_token)
        elif client_secret:
            self._token = self._acquire_token_client_credentials(
                client_id, tenant_id, client_secret)
        else:
            self._init_error = "Outlook not linked."

    def _acquire_token_by_refresh(
        self,
        client_id: str,
        tenant_id: str,
        client_secret: str,
        refresh_token: str,
    ) -> Optional[str]:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.PublicClientApplication(client_id, authority=authority)
        result = app.acquire_token_by_refresh_token(
            refresh_token, scopes=_SCOPE_CALENDAR)
        if "access_token" in result:
            if result.get("refresh_token") and result["refresh_token"] != refresh_token:
                save_refresh_token(str(result["refresh_token"]))     # Microsoft rotates it
            return str(result["access_token"])
        self._init_error = f"Token refresh failed: {result.get('error_description')}"
        logger.warning("event=outlook_refresh_failed %s", self._init_error)
        return None

    def _acquire_token_client_credentials(self, client_id: str, tenant_id: str, client_secret: str) -> Optional[str]:
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret,
        )
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"])
        if "access_token" in result:
            return str(result["access_token"])
        self._init_error = f"Client credentials failed: {result.get('error_description')}"
        logger.warning(
            "event=outlook_client_credentials_failed %s", self._init_error)
        return None

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _events_url(self, calendar_id: str) -> str:
        who = "me" if self._user_id == "me" else f"users/{self._user_id}"
        if calendar_id == "primary" or not calendar_id:
            return f"{_GRAPH_BASE}/{who}/calendar/events"
        return f"{_GRAPH_BASE}/{who}/calendars/{calendar_id}/events"

    def _get(self, url: str, params: dict | None = None) -> dict:
        resp = _requests.get(
            url, headers=self._auth_headers(), params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, body: dict) -> dict:
        resp = _requests.post(
            url, json=body, headers=self._auth_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_outlook_event_body(event: CalendarEvent) -> dict:
    body: dict = {
        "subject": event.title,
        "start": {"dateTime": _to_iso(event.start_datetime), "timeZone": event.timezone},
        "end": {"dateTime": _to_iso(event.end_datetime), "timeZone": event.timezone},
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
        patch["start"] = {"dateTime": updates["start_datetime"],
                          "timeZone": updates.get("timezone", "UTC")}
    if "end_datetime" in updates:
        patch["end"] = {"dateTime": updates["end_datetime"],
                        "timeZone": updates.get("timezone", "UTC")}
    return patch


def _outlook_item_to_record(item: dict) -> CalendarEventRecord:
    start = item.get("start", {})
    end = item.get("end", {})
    body = item.get("body", {})
    loc = item.get("location", {})
    return CalendarEventRecord(
        provider="outlook",
        event_id=str(item.get("id", "")),
        title=item.get("subject"),
        description=body.get("content") if isinstance(body, dict) else None,
        start_datetime=start.get("dateTime"),
        end_datetime=end.get("dateTime"),
        location=loc.get("displayName") if isinstance(loc, dict) else None,
        html_link=item.get("webLink"),
    )

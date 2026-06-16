from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from providers.base import AbstractCalendarProvider
from schemas.calendar_events import CalendarEvent, CalendarEventRecord

logger = logging.getLogger("hestia_hecate.google")

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    _GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    _GOOGLE_LIBS_AVAILABLE = False


_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Persistent token storage path — the ``data/`` directory is volume-mounted
# in docker-compose.yml, so tokens written here survive container restarts.
_TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "/code/data/google_token.json"))
_TOKEN_FILE_LOCK = threading.Lock()


class GoogleCalendarProvider(AbstractCalendarProvider):
    def __init__(self) -> None:
        self._service = None
        self._init_error: Optional[str] = None
        self._setup()

    @property
    def name(self) -> str:
        return "google"

    def is_available(self) -> bool:
        return self._service is not None

    def create_event(self, event: CalendarEvent, calendar_id: str = "primary") -> str:
        body = _build_google_event_body(event)
        result = self._service.events().insert(
            calendarId=calendar_id, body=body).execute()
        return str(result.get("id", ""))

    def list_events(
        self,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> list[CalendarEventRecord]:
        response = (
            self._service.events()
            .list(
                calendarId=calendar_id,
                timeMin=_to_rfc3339(start),
                timeMax=_to_rfc3339(end),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [_google_item_to_record(item) for item in response.get("items", [])]

    def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        try:
            self._service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return True
        except Exception as exc:
            if "404" in str(exc):
                return False
            raise RuntimeError(f"Google delete failed: {exc}") from exc

    def update_event(self, event_id: str, updates: dict, calendar_id: str = "primary") -> bool:
        existing = self._service.events().get(
            calendarId=calendar_id, eventId=event_id).execute()
        patch = _build_google_patch_body(updates, existing)
        self._service.events().patch(calendarId=calendar_id,
                                     eventId=event_id, body=patch).execute()
        return True

    def _setup(self) -> None:
        if not _GOOGLE_LIBS_AVAILABLE:
            self._init_error = "google-api-python-client not installed"
            logger.warning(
                "event=google_provider_lib_missing Google libs not installed")
            return

        creds = self._load_credentials()
        if creds is None:
            return

        try:
            self._service = build(
                "calendar", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning(
                "event=google_provider_build_failed Failed to build Google service: %s", exc)

    def refresh(self) -> bool:
        """Re-load and refresh Google credentials; rebuild the API service client."""
        logger.info(
            "event=google_provider_refresh Refreshing Google credentials")
        self._service = None
        self._init_error = None
        self._setup()
        available = self.is_available()
        logger.info("event=google_provider_refresh_result available=%s error=%s",
                    available, self._init_error)
        return available

    # ------------------------------------------------------------------
    # Public helpers (used by main.py OAuth completion flow)
    # ------------------------------------------------------------------

    @staticmethod
    def persist_token(token_data: dict) -> None:
        """Write *token_data* to the persistent file and update env vars.

        Updates both ``GOOGLE_TOKEN_JSON`` (process lifetime) and
        ``GOOGLE_REFRESH_TOKEN`` (so the individual env var stays in sync
        with any rotated refresh token).

        Thread-safe — uses a module-level lock so concurrent calendar
        operations don't interleave writes.
        """
        serialized = json.dumps(token_data, indent=2)
        with _TOKEN_FILE_LOCK:
            try:
                _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                _TOKEN_FILE.write_text(serialized, encoding="utf-8")
                logger.info(
                    "event=google_token_persisted path=%s", _TOKEN_FILE)
            except Exception as exc:
                logger.warning(
                    "event=google_token_persist_failed path=%s error=%s",
                    _TOKEN_FILE, exc)
        os.environ["GOOGLE_TOKEN_JSON"] = json.dumps(token_data)
        if token_data.get("refresh_token"):
            os.environ["GOOGLE_REFRESH_TOKEN"] = token_data["refresh_token"]

    @staticmethod
    def _try_load_cached_token() -> dict | None:
        """Return cached token data from the persistent file (if it exists
        and has a still-valid access token).  This is an optimisation to
        skip the refresh API call on restart when the cached access token
        hasn't expired yet.

        Returns ``None`` when no usable cache is found — the caller should
        fall through to building fresh credentials from the non-expiring
        env vars.
        """
        if not _TOKEN_FILE.exists():
            return None
        try:
            raw = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            if not raw:
                return None
            data = json.loads(raw)
            # If the cached access token is still valid, return it so the
            # caller can skip the refresh round-trip.
            creds = Credentials.from_authorized_user_info(data, _SCOPES)
            if creds.valid:
                logger.info(
                    "event=google_token_cached_valid path=%s", _TOKEN_FILE)
                return data
            logger.info(
                "event=google_token_cached_expired path=%s", _TOKEN_FILE)
        except Exception as exc:
            logger.warning(
                "event=google_token_cache_read_error path=%s error=%s",
                _TOKEN_FILE, exc)
        return None

    # ------------------------------------------------------------------
    # Internal credential loading
    # ------------------------------------------------------------------

    def _load_credentials(self):
        # 1) Service account (JSON key file contents in env var)
        sa_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip(
        ) or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if sa_json:
            try:
                info = json.loads(sa_json)
                logger.info("event=google_auth_mode mode=service_account")
                return service_account.Credentials.from_service_account_info(
                    info, scopes=_SCOPES)
            except Exception as exc:
                self._init_error = f"Service account parse error: {exc}"
                logger.warning(
                    "event=google_service_account_parse_failed %s", self._init_error)
                return None

        # 2) Try the persistent cache first — if the cached access token
        #    from a previous run is still valid we skip the refresh call.
        cached = self._try_load_cached_token()
        if cached is not None:
            try:
                creds = Credentials.from_authorized_user_info(cached, _SCOPES)
                logger.info(
                    "event=google_auth_mode mode=cached_token "
                    "expiry=%s", getattr(creds, "expiry", None))
                return creds
            except Exception as exc:
                logger.warning(
                    "event=google_cached_token_parse_failed %s", exc)
                # Fall through — build from canonical env vars

        # 3) Build credentials from the canonical, non-expiring env vars.
        #    These are the SOURCE OF TRUTH — no stale access token needed.
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()

        # If the persistent cache file exists, prefer its refresh_token over
        # the env var — the cache is always updated after every successful
        # refresh, while the .env file may contain a stale/dead value.
        if _TOKEN_FILE.exists():
            try:
                cached_raw = _TOKEN_FILE.read_text(encoding="utf-8").strip()
                if cached_raw:
                    cached_data = json.loads(cached_raw)
                    cached_rt = cached_data.get("refresh_token", "").strip()
                    if cached_rt:
                        refresh_token = cached_rt
                        client_id = client_id or cached_data.get("client_id", "")
                        client_secret = client_secret or cached_data.get("client_secret", "")
                        logger.info(
                            "event=google_using_cached_refresh_token")
            except Exception:
                pass

        # Also check GOOGLE_TOKEN_JSON as a bundled alternative.
        token_json = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
        if token_json and not refresh_token:
            try:
                bundled = json.loads(token_json)
                client_id = client_id or bundled.get("client_id", "")
                client_secret = client_secret or bundled.get("client_secret", "")
                refresh_token = refresh_token or bundled.get("refresh_token", "")
            except Exception:
                pass

        if not client_id or not client_secret:
            self._init_error = (
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set")
            logger.warning(
                "event=google_missing_client_creds %s", self._init_error)
            return None

        if not refresh_token:
            self._init_error = (
                "GOOGLE_REFRESH_TOKEN must be set "
                "(run OAuth initiate/complete flow to obtain one)")
            logger.warning(
                "event=google_missing_refresh_token %s", self._init_error)
            return None

        # Build credentials with NO access token — the refresh_token is
        # the only long-lived secret needed.  creds.expired will be True,
        # triggering a refresh below.
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=_SCOPES,
        )

        logger.info(
            "event=google_auth_mode mode=refresh_token "
            "client_id=%s container_utc=%s",
            client_id,
            datetime.now(timezone.utc).isoformat())

        try:
            creds.refresh(Request())
            logger.info(
                "event=google_token_refreshed "
                "new_expiry=%s",
                getattr(creds, "expiry", None),
            )
            # Persist the fresh access token + refresh token so the next
            # cold start can hit the cache and skip this refresh call.
            refreshed_data = _credentials_to_json_dict(creds)
            self.persist_token(refreshed_data)
        except Exception as exc:
            self._init_error = f"OAuth token refresh error: {exc}"
            logger.warning(
                "event=google_oauth_refresh_failed %s", self._init_error)
            return None

        return creds


def _credentials_to_json_dict(creds) -> dict:
    """Serialize a :class:`google.oauth2.credentials.Credentials` object to the
    canonical ``GOOGLE_TOKEN_JSON`` dict shape for persistence."""
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": getattr(creds, "token_uri",
                              "https://oauth2.googleapis.com/token"),
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or _SCOPES),
    }


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
        body["start"] = {"dateTime": _to_rfc3339(
            event.start_datetime), "timeZone": event.timezone}
        body["end"] = {"dateTime": _to_rfc3339(
            event.end_datetime), "timeZone": event.timezone}

    if event.reminders_minutes_before:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": m} for m in event.reminders_minutes_before],
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
        event_id=str(item.get("id", "")),
        title=item.get("summary"),
        description=item.get("description"),
        start_datetime=start.get("dateTime") or start.get("date"),
        end_datetime=end.get("dateTime") or end.get("date"),
        location=item.get("location"),
        html_link=item.get("htmlLink"),
    )

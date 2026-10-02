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


_SCOPES = [
    s for s in os.getenv("GOOGLE_OAUTH_SCOPES", "").replace(",", " ").split() if s
] or ["https://www.googleapis.com/auth/calendar"]

# Persistent token storage path — the ``data/`` directory is volume-mounted
# in docker-compose.yml, so tokens written here survive container restarts.
_TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "/code/data/google_token.json"))
_TOKEN_FILE_LOCK = threading.Lock()


def has_stored_token() -> bool:
    """True when the persistent token file holds a refresh token."""
    try:
        if not _TOKEN_FILE.exists():
            return False
        data = json.loads(_TOKEN_FILE.read_text(encoding="utf-8") or "{}")
        return bool(isinstance(data, dict) and data.get("refresh_token"))
    except Exception:
        return False


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

    # ------------------------------------------------------------------
    # Internal credential loading
    # ------------------------------------------------------------------

    @staticmethod
    def _read_token_file() -> dict | None:
        if not _TOKEN_FILE.exists():
            return None
        try:
            raw = _TOKEN_FILE.read_text(encoding="utf-8").strip()
            data = json.loads(raw) if raw else None
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.warning(
                "event=google_token_cache_read_error path=%s error=%s",
                _TOKEN_FILE, exc)
            return None

    @staticmethod
    def _candidate_tokens() -> list[tuple[str, dict]]:
        """Authorized-user token candidates, most trusted first.

        1. Persistent file (written by OAuth complete, host helper, or a
           previous refresh) — always the most recent.
        2. ``GOOGLE_REFRESH_TOKEN`` env var.
        3. ``GOOGLE_TOKEN_JSON`` env var (bundled JSON).

        Duplicates (same refresh token) are dropped.  Missing client id/secret
        are filled from the canonical env vars.
        """
        env_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        env_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        raw: list[tuple[str, dict]] = []

        file_data = GoogleCalendarProvider._read_token_file()
        if file_data:
            raw.append(("file", file_data))
        env_rt = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
        if env_rt:
            raw.append(("env_refresh_token", {"refresh_token": env_rt}))
        token_json = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
        if token_json:
            try:
                bundled = json.loads(token_json)
                if isinstance(bundled, dict):
                    raw.append(("env_token_json", bundled))
            except Exception as exc:
                logger.warning("event=google_token_json_parse_failed error=%s", exc)

        seen: set[str] = set()
        out: list[tuple[str, dict]] = []
        for source, data in raw:
            rt = str(data.get("refresh_token") or "").strip()
            if not rt or rt in seen:
                continue
            seen.add(rt)
            merged = dict(data)
            # Env client creds win: the token file may carry an old client.
            merged["client_id"] = env_id or str(data.get("client_id") or "")
            merged["client_secret"] = env_secret or str(data.get("client_secret") or "")
            merged.setdefault("token_uri", "https://oauth2.googleapis.com/token")
            out.append((source, merged))
        return out

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

        # 2) Authorized-user tokens (OAuth refresh token).
        candidates = self._candidate_tokens()
        if not candidates:
            self._init_error = (
                "Google not authorized yet: no refresh token found. Run the OAuth "
                "flow (POST /api/gateway/auth/initiate/google, or google-oauth.bat on the host)")
            logger.warning("event=google_missing_refresh_token %s", self._init_error)
            return None

        errors: list[str] = []
        for source, data in candidates:
            if not data.get("client_id") or not data.get("client_secret"):
                errors.append(f"{source}: GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET missing")
                continue
            try:
                creds = Credentials.from_authorized_user_info(data, data.get("scopes") or _SCOPES)
            except Exception as exc:
                errors.append(f"{source}: unreadable token ({exc})")
                continue

            # A cached access token with a known future expiry is reusable.
            if creds.valid and getattr(creds, "expiry", None) is not None:
                logger.info("event=google_auth_mode mode=cached_token source=%s expiry=%s",
                            source, creds.expiry)
                return creds

            try:
                creds.refresh(Request())
            except Exception as exc:
                msg = str(exc)
                if "invalid_grant" in msg:
                    msg += (" — refresh token revoked or expired. If the OAuth consent screen is in "
                            "'Testing' mode Google expires tokens after 7 days: set it to "
                            "'In production', then re-run the OAuth flow.")
                errors.append(f"{source}: {msg}")
                logger.warning("event=google_oauth_refresh_failed source=%s error=%s", source, msg)
                continue

            logger.info("event=google_token_refreshed source=%s new_expiry=%s",
                        source, getattr(creds, "expiry", None))
            self.persist_token(_credentials_to_json_dict(creds))
            return creds

        self._init_error = "OAuth token refresh error: " + " | ".join(errors)
        return None


def _credentials_to_json_dict(creds) -> dict:
    """Serialize a :class:`google.oauth2.credentials.Credentials` object to the
    canonical ``GOOGLE_TOKEN_JSON`` dict shape for persistence.

    ``expiry`` must be stored: without it google-auth treats any cached access
    token as valid forever and the first call after a restart gets a 401.
    """
    expiry = getattr(creds, "expiry", None)
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": getattr(creds, "token_uri",
                              "https://oauth2.googleapis.com/token"),
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or _SCOPES),
        "expiry": (expiry.isoformat() + "Z") if expiry else None,
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

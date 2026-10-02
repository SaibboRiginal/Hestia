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

GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GoogleMailAuthError(Exception):
    """Gmail API auth failure — missing scopes or invalid credentials.

    Not transient: the caller returns a user-facing error with a re-auth button
    (or falls back to IMAP when configured).
    """

try:
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    _GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    _GOOGLE_LIBS_AVAILABLE = False


_SCOPES = [
    s for s in os.getenv("GOOGLE_OAUTH_SCOPES", "").replace(",", " ").split() if s
] or ["https://www.googleapis.com/auth/calendar", GMAIL_READ_SCOPE]

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
        creds, error = load_google_credentials()
        self._init_error = error
        return creds


def load_google_credentials():
    """Return ``(credentials, error)``. Shared by Calendar and Gmail.

    Order: service account → authorized-user token candidates (file, env).
    The token's own scopes are used (requesting scopes it was never granted
    makes Google answer ``invalid_scope``).  A refresh token Google rejects
    with ``invalid_grant`` is dropped from the token file, so the next OAuth
    flow starts clean.
    """
    if not _GOOGLE_LIBS_AVAILABLE:
        return None, "google-api-python-client not installed"
    sa_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip(
    ) or os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_json:
        try:
            info = json.loads(sa_json)
            logger.info("event=google_auth_mode mode=service_account")
            return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES), None
        except Exception as exc:
            error = f"Service account parse error: {exc}"
            logger.warning("event=google_service_account_parse_failed %s", error)
            return None, error

    candidates = GoogleCalendarProvider._candidate_tokens()
    if not candidates:
        error = ("Google not authorized yet: no refresh token found. Run the OAuth flow "
                 "(Telegram: Connetti Google, or POST /api/gateway/auth/initiate/google)")
        logger.warning("event=google_missing_refresh_token %s", error)
        return None, error

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
            return creds, None

        try:
            creds.refresh(Request())
        except Exception as exc:
            msg = str(exc)
            if "invalid_grant" in msg:
                msg += (" — refresh token revoked or expired. If the OAuth consent screen is in "
                        "'Testing' mode Google expires tokens after 7 days: set it to "
                        "'In production', then re-run the OAuth flow.")
                if source == "file":
                    _drop_token_file("invalid_grant")
                else:
                    os.environ.pop("GOOGLE_TOKEN_JSON" if source == "env_token_json"
                                   else "GOOGLE_REFRESH_TOKEN", None)
            elif "invalid_scope" in msg:
                msg += " — token lacks the requested scopes: re-run the OAuth flow."
            errors.append(f"{source}: {msg}")
            logger.warning("event=google_oauth_refresh_failed source=%s error=%s", source, msg)
            continue

        logger.info("event=google_token_refreshed source=%s new_expiry=%s scopes=%s",
                    source, getattr(creds, "expiry", None), list(creds.scopes or []))
        GoogleCalendarProvider.persist_token(_credentials_to_json_dict(creds))
        return creds, None

    return None, "OAuth token refresh error: " + " | ".join(errors)


def _drop_token_file(reason: str) -> None:
    with _TOKEN_FILE_LOCK:
        try:
            if _TOKEN_FILE.exists():
                _TOKEN_FILE.unlink()
                logger.info("event=google_token_file_deleted reason=%s path=%s", reason, _TOKEN_FILE)
        except Exception as exc:
            logger.warning("event=google_token_file_delete_failed path=%s error=%s", _TOKEN_FILE, exc)


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


# ---------------------------------------------------------------------------
# Gmail API provider
# ---------------------------------------------------------------------------

_IMAP_TO_GMAIL = [
    (r'\bFROM\s+"([^"]+)"', r"from:(\1)"),
    (r'\bTO\s+"([^"]+)"', r"to:(\1)"),
    (r'\bSUBJECT\s+"([^"]+)"', r'subject:("\1")'),
    (r'\b(?:TEXT|BODY)\s+"([^"]+)"', r'"\1"'),
    (r"\bUNSEEN\b", "is:unread"),
    (r"\bSEEN\b", "is:read"),
]
_IMAP_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def imap_to_gmail_query(query: str) -> str:
    """Translate simple IMAP criteria (what Scout/connectors send) to Gmail search.

    ``FROM "a@b.it"`` → ``from:(a@b.it)``; ``SINCE 01-Jan-2026`` → ``after:2026/01/01``.
    Free text passes through unchanged.
    """
    import re

    q = str(query or "").strip()
    if not q:
        return ""
    q = q.strip("()").strip()
    for pattern, repl in _IMAP_TO_GMAIL:
        q = re.sub(pattern, repl, q, flags=re.I)

    def _since(m):
        day, mon, year = m.group(1), m.group(2).lower()[:3], m.group(3)
        return f"after:{year}/{_IMAP_MONTHS.get(mon, 1):02d}/{int(day):02d}"

    q = re.sub(r"\bSINCE\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})", _since, q, flags=re.I)
    return re.sub(r"\s+", " ", q).strip()


def _gmail_body(payload: dict) -> str:
    import base64

    texts: list[str] = []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime in {"text/plain", "text/html"}:
            try:
                texts.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
                             .decode("utf-8", errors="ignore"))
            except Exception:
                pass
        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})
    return "\n\n".join(t for t in texts if t).strip()


class GoogleMailProvider:
    """Gmail API provider (read: gmail.readonly; send only with gmail.send)."""

    def __init__(self) -> None:
        self._service = None
        self._scopes: set[str] = set()
        self._init_error: Optional[str] = None
        self._setup()

    @property
    def name(self) -> str:
        return "gmail_api"

    def is_available(self) -> bool:
        return self._service is not None

    @property
    def can_send(self) -> bool:
        return self.is_available() and GMAIL_SEND_SCOPE in self._scopes

    def status(self) -> dict:
        return {"available": self.is_available(), "can_send": self.can_send,
                "error": None if self.is_available() else self._init_error}

    def _setup(self) -> None:
        creds, error = load_google_credentials()
        if creds is None:
            self._init_error = error or "No Google credentials"
            return
        self._scopes = set(getattr(creds, "scopes", None) or [])
        if GMAIL_READ_SCOPE not in self._scopes and "https://mail.google.com/" not in self._scopes:
            self._init_error = (
                f"Gmail scope '{GMAIL_READ_SCOPE}' not granted (granted: {sorted(self._scopes)}). "
                "Re-authorize Google and allow 'read your email'.")
            logger.error("event=gmail_setup_missing_scope granted_scopes=%s", sorted(self._scopes))
            return
        try:
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        except Exception as exc:
            self._init_error = str(exc)
            logger.warning("event=gmail_provider_build_failed error=%s", exc)

    def _auth_error(self, exc) -> GoogleMailAuthError:
        logger.error("event=gmail_auth_failed status=%s reason=%s", exc.resp.status, exc)
        return GoogleMailAuthError(
            f"Gmail API returned {exc.resp.status}: insufficient permissions or revoked token. "
            "Re-authorize Google (calendar + gmail.readonly).")

    def _row(self, msg_id: str, full: bool) -> dict:
        from email.utils import parsedate_to_datetime

        detail = self._service.users().messages().get(
            userId="me", id=msg_id, format="full" if full else "metadata",
            metadataHeaders=["Subject", "From", "To", "Date", "Message-ID"]).execute()
        payload = detail.get("payload", {}) or {}
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        try:
            created = parsedate_to_datetime(headers.get("date", "")).astimezone(timezone.utc).isoformat()
        except Exception:
            ms = int(detail.get("internalDate") or 0)
            created = (datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms
                       else datetime.now(timezone.utc)).isoformat()
        body = _gmail_body(payload) if full else ""
        return {
            "id": msg_id,
            "message_id": headers.get("message-id", ""),
            "thread_id": detail.get("threadId", ""),
            "subject": headers.get("subject", "") or "No Subject",
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "created_at": created,
            "snippet": detail.get("snippet", ""),
            "body": body or detail.get("snippet", ""),
            "direction": "inbound",
        }

    def list_messages(self, q: str = "", limit: int = 20, since: datetime | None = None,
                      full: bool = True) -> list[dict]:
        """Search Gmail. ``q`` = Gmail syntax or simple IMAP criteria (translated)."""
        if not self._service:
            raise GoogleMailAuthError(self._init_error or "Gmail provider not available")
        query = imap_to_gmail_query(q)
        if since:
            query = f"{query} after:{int(since.timestamp())}".strip()
        try:
            params = {"userId": "me", "maxResults": max(1, min(int(limit), 500))}
            if query:
                params["q"] = query
            results = self._service.users().messages().list(**params).execute()
            out = [self._row(m["id"], full) for m in results.get("messages", [])[:limit]]
            logger.info("event=gmail_search_done query=%s results=%d", query, len(out))
            return out
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                raise self._auth_error(exc) from exc
            logger.warning("event=gmail_list_http_error status=%s error=%s", exc.resp.status, exc)
            raise RuntimeError(f"Gmail API error {exc.resp.status}") from exc

    def get_message(self, message_id: str) -> dict | None:
        if not self._service:
            raise GoogleMailAuthError(self._init_error or "Gmail provider not available")
        try:
            return self._row(message_id, True)
        except HttpError as exc:
            if exc.resp.status == 404:
                return None
            if exc.resp.status in (401, 403):
                raise self._auth_error(exc) from exc
            raise RuntimeError(f"Gmail API error {exc.resp.status}") from exc

    def send(self, to: str, subject: str, body: str) -> dict:
        import base64
        from email.message import EmailMessage

        if not self.can_send:
            raise GoogleMailAuthError("Gmail send not authorized (scope gmail.send missing)")
        msg = EmailMessage()
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        try:
            sent = self._service.users().messages().send(userId="me", body={"raw": raw}).execute()
        except HttpError as exc:
            if exc.resp.status in (401, 403):
                raise self._auth_error(exc) from exc
            raise RuntimeError(f"Gmail send error {exc.resp.status}") from exc
        return {"id": sent.get("id", ""), "to": to, "subject": subject,
                "created_at": datetime.now(timezone.utc).isoformat(), "direction": "outbound"}

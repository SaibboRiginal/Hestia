"""Mail gateway — Gmail via the Google OAuth token only (no IMAP / app passwords).

Iris (email domain) and the ``iris_email`` connector (Scout) reach mail only
through Hecate. Read needs scope gmail.readonly, send needs gmail.send (both in
the default GOOGLE_OAUTH_SCOPES).
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from providers.google import GoogleMailAuthError, GoogleMailProvider


class MailUnavailable(Exception):
    """Gmail cannot serve the request (``auth_required`` → offer re-auth)."""

    def __init__(self, message: str, auth_required: bool = False):
        super().__init__(message)
        self.auth_required = auth_required


class MailGateway:
    def __init__(self) -> None:
        self._gmail: GoogleMailProvider | None = None
        self._lock = threading.Lock()

    def gmail(self) -> GoogleMailProvider:
        with self._lock:
            if self._gmail is None:
                self._gmail = GoogleMailProvider()
            return self._gmail

    def reset(self) -> None:
        """Rebuild Gmail on next use (new token / scopes)."""
        with self._lock:
            self._gmail = None

    def status(self) -> dict[str, Any]:
        gmail = self.gmail()
        return {"backend": "gmail_api" if gmail.is_available() else None,
                "gmail_api": gmail.status(), "can_send": gmail.can_send}

    def search(self, q: str = "", since: datetime | None = None, limit: int = 50) -> tuple[list[dict], str]:
        gmail = self.gmail()
        if not gmail.is_available():
            raise MailUnavailable(gmail._init_error or "Gmail not authorized", auth_required=True)
        try:
            return gmail.list_messages(q=q, limit=limit, since=since), "gmail_api"
        except GoogleMailAuthError as exc:
            self.reset()
            raise MailUnavailable(str(exc), auth_required=True)
        except Exception as exc:
            raise MailUnavailable(f"Gmail API error: {exc}")

    def get(self, message_id: str) -> dict | None:
        gmail = self.gmail()
        try:
            if not message_id.startswith("<") and "@" not in message_id:
                return gmail.get_message(message_id)
            rows, _ = self.search(q=f"rfc822msgid:{message_id.strip('<>')}", limit=5)
            return rows[0] if rows else None
        except GoogleMailAuthError as exc:
            raise MailUnavailable(str(exc), auth_required=True)

    def send(self, to: str, subject: str, body: str) -> tuple[dict, str]:
        gmail = self.gmail()
        try:
            return gmail.send(to, subject, body), "gmail_api"
        except GoogleMailAuthError as exc:
            raise MailUnavailable(f"{exc} — re-authorize Google to grant gmail.send", auth_required=True)
        except Exception as exc:
            raise MailUnavailable(f"Gmail send error: {exc}")


mail_gateway = MailGateway()

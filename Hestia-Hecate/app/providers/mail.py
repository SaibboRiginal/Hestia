"""Mail gateway — one entry point over the two mail backends Hecate owns.

- ``gmail_api``: Gmail API with the Google OAuth token (scope gmail.readonly;
  sending also needs gmail.send).  Primary when authorized.
- ``imap``: IMAP/SMTP with an app password (GMAIL_ADDRESS + GMAIL_APP_PASSWORD
  or HECATE_IMAP_*).  Fallback for reading, primary for sending.

Iris (email domain) and the ``iris_email`` connector (Scout) reach mail only
through Hecate, which picks the backend here.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from providers.google import GoogleMailAuthError, GoogleMailProvider
from providers.mail_imap import ImapMailProvider, MailProviderError

logger = logging.getLogger("hestia_hecate.mail_gateway")


class MailUnavailable(Exception):
    """No mail backend can serve the request (``auth_required`` → offer re-auth)."""

    def __init__(self, message: str, auth_required: bool = False):
        super().__init__(message)
        self.auth_required = auth_required


class MailGateway:
    def __init__(self) -> None:
        self._gmail: GoogleMailProvider | None = None
        self._lock = threading.Lock()

    # ── backends ────────────────────────────────────────────────────────────
    def gmail(self) -> GoogleMailProvider:
        with self._lock:
            if self._gmail is None:
                self._gmail = GoogleMailProvider()
            return self._gmail

    def reset(self) -> None:
        """Rebuild Gmail on next use (new token / scopes)."""
        with self._lock:
            self._gmail = None

    @staticmethod
    def imap() -> ImapMailProvider:
        return ImapMailProvider()

    def status(self) -> dict[str, Any]:
        gmail, imap = self.gmail(), self.imap()
        backend = "gmail_api" if gmail.is_available() else ("imap" if imap.configured else None)
        return {"backend": backend, "gmail_api": gmail.status(), "imap": imap.status(),
                "can_send": gmail.can_send or bool(imap.configured and imap.smtp_host)}

    # ── operations ──────────────────────────────────────────────────────────
    def search(self, q: str = "", since: datetime | None = None, limit: int = 50) -> tuple[list[dict], str]:
        gmail, imap = self.gmail(), self.imap()
        gmail_error = None
        if gmail.is_available():
            try:
                return gmail.list_messages(q=q, limit=limit, since=since), "gmail_api"
            except GoogleMailAuthError as exc:
                gmail_error = str(exc)
                self.reset()
                if not imap.configured:
                    raise MailUnavailable(gmail_error, auth_required=True)
                logger.warning("[🔄] event=mail_gmail_auth_failed_fallback_imap error=%s", exc)
            except Exception as exc:
                if not imap.configured:
                    raise MailUnavailable(f"Gmail API error: {exc}")
                logger.warning("[🔄] event=mail_gmail_failed_fallback_imap error=%s", exc)
        else:
            gmail_error = gmail._init_error
        if imap.configured:
            try:
                return imap.search(query=q, since=since, limit=limit), "imap"
            except MailProviderError as exc:
                raise MailUnavailable(str(exc))
        raise MailUnavailable(
            gmail_error or "No mail backend configured: authorize Google (Gmail) or set "
            "GMAIL_ADDRESS + GMAIL_APP_PASSWORD", auth_required=True)

    def get(self, message_id: str) -> dict | None:
        gmail = self.gmail()
        if gmail.is_available() and not message_id.startswith("<") and "@" not in message_id:
            try:
                return gmail.get_message(message_id)
            except GoogleMailAuthError as exc:
                raise MailUnavailable(str(exc), auth_required=True)
        rows, _ = self.search(q=f'HEADER Message-ID "{message_id}"', limit=5)
        return next((r for r in rows if str(r.get("id")) == message_id
                     or str(r.get("message_id")) == message_id), rows[0] if rows else None)

    def send(self, to: str, subject: str, body: str) -> tuple[dict, str]:
        imap, gmail = self.imap(), self.gmail()
        if imap.configured and imap.smtp_host:
            try:
                return imap.send(to, subject, body), "smtp"
            except MailProviderError as exc:
                if not gmail.can_send:
                    raise MailUnavailable(str(exc))
                logger.warning("[🔄] event=mail_smtp_failed_fallback_gmail error=%s", exc)
        if gmail.can_send:
            try:
                return gmail.send(to, subject, body), "gmail_api"
            except GoogleMailAuthError as exc:
                raise MailUnavailable(str(exc), auth_required=True)
        raise MailUnavailable(
            "No send backend: set GMAIL_ADDRESS + GMAIL_APP_PASSWORD (SMTP) or add scope "
            "gmail.send to GOOGLE_OAUTH_SCOPES and re-authorize")


mail_gateway = MailGateway()

"""IMAP/SMTP mail provider (Gmail app password or any IMAP server).

Hecate owns provider runtime: Iris (email domain) and the ``iris_email``
connector (Scout) reach mail only through here.  Restores the Gmail IMAP
fetch that was lost in the Ingest → Hecate refactor (Scout received no mail).

Config (env):
    GMAIL_ADDRESS + GMAIL_APP_PASSWORD           Gmail shortcut (imap/smtp.gmail.com)
    HECATE_IMAP_HOST / _PORT / _USER / _PASSWORD  generic IMAP (overrides Gmail)
    HECATE_SMTP_HOST / _PORT                     generic SMTP (STARTTLS); user/pass = IMAP's
    HECATE_IMAP_FOLDER                           default INBOX
"""
from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import smtplib
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

logger = logging.getLogger("hestia_hecate.mail")

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Raw IMAP SEARCH keys a caller may pass as a filter (Scout sends 'FROM "x"').
_IMAP_KEYS = re.compile(r"^\s*\(?\s*(FROM|TO|SUBJECT|BODY|TEXT|SINCE|BEFORE|ON|UNSEEN|SEEN|OR|NOT|HEADER|CC)\b", re.I)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _body(msg: email.message.Message) -> str:
    parts: list[str] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        except Exception as exc:
            logger.warning("event=mail_part_decode_failed error=%s", exc)
    return "\n\n".join(parts).strip()


def _quote(text: str) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


class MailProviderError(Exception):
    pass


class ImapMailProvider:
    def __init__(self) -> None:
        gmail = os.getenv("GMAIL_ADDRESS", "").strip()
        self.user = os.getenv("HECATE_IMAP_USER", "").strip() or gmail
        self.password = (os.getenv("HECATE_IMAP_PASSWORD", "").strip()
                         or os.getenv("GMAIL_APP_PASSWORD", "").strip().replace(" ", ""))
        self.imap_host = os.getenv("HECATE_IMAP_HOST", "").strip() or ("imap.gmail.com" if gmail else "")
        self.imap_port = int(os.getenv("HECATE_IMAP_PORT", "993"))
        self.smtp_host = os.getenv("HECATE_SMTP_HOST", "").strip() or ("smtp.gmail.com" if gmail else "")
        self.smtp_port = int(os.getenv("HECATE_SMTP_PORT", "587"))
        self.folder = os.getenv("HECATE_IMAP_FOLDER", "INBOX")

    @property
    def configured(self) -> bool:
        return bool(self.user and self.password and self.imap_host)

    def status(self) -> dict[str, Any]:
        return {"configured": self.configured, "user": self.user or None,
                "imap_host": self.imap_host or None, "smtp_host": self.smtp_host or None}

    def _require(self) -> None:
        if not self.configured:
            raise MailProviderError(
                "Mail provider not configured: set GMAIL_ADDRESS + GMAIL_APP_PASSWORD "
                "(Google account → Security → App passwords) or HECATE_IMAP_* in Hecate .env")

    @staticmethod
    def build_criteria(query: str = "", since: datetime | None = None) -> str:
        """Raw IMAP criteria pass through ('FROM "x"'); free text → TEXT search."""
        parts: list[str] = []
        if since:
            parts.append(f"SINCE {since.day:02d}-{_MONTHS[since.month - 1]}-{since.year}")
        q = str(query or "").strip()
        if q:
            parts.append(q if _IMAP_KEYS.match(q) else f"TEXT {_quote(q)}")
        return f"({' '.join(parts)})" if parts else "ALL"

    def search(self, query: str = "", since: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self._require()
        criteria = self.build_criteria(query, since)
        try:
            conn = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        except Exception as exc:
            raise MailProviderError(f"IMAP connect failed: {exc}")
        try:
            conn.login(self.user, self.password)
            conn.select(self.folder, readonly=True)       # never mark mail as read
            status, data = conn.search(None, criteria)
            if status != "OK" or not data or not data[0]:
                return []
            ids = data[0].split()[-max(1, min(limit, 500)):]  # newest last → keep the most recent
            out: list[dict[str, Any]] = []
            for msg_id in reversed(ids):
                status, msg_data = conn.fetch(msg_id, "(BODY.PEEK[])")
                raw = next((p[1] for p in msg_data or [] if isinstance(p, tuple)), None)
                if status != "OK" or not raw:
                    continue
                msg = email.message_from_bytes(raw)
                try:
                    created = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).isoformat()
                except Exception:
                    created = datetime.now(timezone.utc).isoformat()
                subject = _decode(msg.get("Subject")) or "No Subject"
                out.append({
                    "id": str(msg.get("Message-ID") or f"imap-{msg_id.decode()}").strip(),
                    "thread_id": re.sub(r"^\s*((re|fwd?|r|i)\s*:\s*)+", "", subject, flags=re.I).strip().lower(),
                    "from": _decode(msg.get("From")),
                    "to": _decode(msg.get("To")),
                    "subject": subject,
                    "body": _body(msg),
                    "created_at": created,
                    "direction": "inbound",
                })
            logger.info("event=mail_search_done criteria=%s results=%d", criteria, len(out))
            return out
        except imaplib.IMAP4.error as exc:
            raise MailProviderError(f"IMAP error: {exc}")
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    def send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        self._require()
        if not self.smtp_host:
            raise MailProviderError("SMTP host not configured (HECATE_SMTP_HOST)")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.user, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                smtp.login(self.user, self.password)
                smtp.send_message(msg)
        except Exception as exc:
            raise MailProviderError(f"SMTP send failed: {exc}")
        logger.info("event=mail_sent to=%s subject_len=%d", to, len(subject))
        return {"id": str(msg.get("Message-ID") or ""), "to": to, "subject": subject,
                "created_at": datetime.now(timezone.utc).isoformat(), "direction": "outbound"}

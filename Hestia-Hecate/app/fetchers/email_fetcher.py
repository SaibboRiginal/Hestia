from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.base_fetcher import BaseFetcher
from providers.mail import MailUnavailable, mail_gateway

logger = logging.getLogger("hestia_hecate.email_fetcher")


class EmailFetcher(BaseFetcher):
    """``iris_email`` connector: raw provider mail for domain modules (Scout).

    Reads Hecate's mail gateway in-process (Gmail API when authorized, IMAP
    fallback — Hecate owns provider runtime).
    It used to call Iris, whose store was an in-memory stub, so Scout always
    received zero mails; it also ignored ``since_date`` and treated IMAP
    filters ('FROM "x"') as free text.
    """

    def connect(self) -> bool:
        st = mail_gateway.status()
        if not st["backend"]:
            logger.warning("[🔄] event=email_fetcher_not_configured No mail backend: authorize Google "
                           "(Gmail) or set GMAIL_ADDRESS/GMAIL_APP_PASSWORD | gmail_error=%s",
                           st["gmail_api"].get("error"))
            return False
        return True

    def fetch_new_data(self, since_date: datetime, custom_filter: str = "") -> list[dict[str, Any]]:
        try:
            rows, backend = mail_gateway.search(q=custom_filter, since=since_date, limit=200)
        except MailUnavailable as exc:
            logger.warning("[🔄] event=email_fetcher_request_failed error=%s", exc)
            raise
        logger.info("event=email_fetcher_done backend=%s results=%d", backend, len(rows))
        return [
            {
                "reference_id": row["id"],
                "source": "email",
                "title": row.get("subject") or "No Subject",
                "sender": row.get("from") or "Unknown Sender",
                "body": row.get("body") or row.get("snippet") or "",
                "timestamp": row.get("created_at"),
            }
            for row in rows
        ]

    def disconnect(self) -> None:
        return

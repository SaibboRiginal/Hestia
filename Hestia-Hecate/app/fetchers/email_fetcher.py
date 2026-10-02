from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from core.base_fetcher import BaseFetcher
from providers.mail_imap import ImapMailProvider, MailProviderError

logger = logging.getLogger("hestia_hecate.email_fetcher")


class EmailFetcher(BaseFetcher):
    """``iris_email`` connector: raw provider mail for domain modules (Scout).

    Reads Hecate's own IMAP provider in-process (Hecate owns provider runtime).
    It used to call Iris, whose store was an in-memory stub, so Scout always
    received zero mails; it also ignored ``since_date`` and treated IMAP
    filters ('FROM "x"') as free text.
    """

    def __init__(self) -> None:
        self.provider = ImapMailProvider()

    def connect(self) -> bool:
        if not self.provider.configured:
            logger.warning("[🔄] event=email_fetcher_not_configured Mail provider not configured "
                           "(GMAIL_ADDRESS/GMAIL_APP_PASSWORD or HECATE_IMAP_*)")
            return False
        return True

    def fetch_new_data(self, since_date: datetime, custom_filter: str = "") -> list[dict[str, Any]]:
        try:
            rows = self.provider.search(query=custom_filter, since=since_date, limit=200)
        except MailProviderError as exc:
            logger.warning("[🔄] event=email_fetcher_request_failed error=%s", exc)
            raise
        return [
            {
                "reference_id": row["id"],
                "source": "email",
                "title": row["subject"],
                "sender": row["from"] or "Unknown Sender",
                "body": row["body"],
                "timestamp": row["created_at"],
            }
            for row in rows
        ]

    def disconnect(self) -> None:
        return

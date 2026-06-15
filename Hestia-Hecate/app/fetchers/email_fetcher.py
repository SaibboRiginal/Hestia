from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

from core.base_fetcher import BaseFetcher

logger = logging.getLogger("hestia_hecate.email_fetcher")


class EmailFetcher(BaseFetcher):
    def __init__(self) -> None:
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self.email_service = os.getenv(
            "HECATE_EMAIL_SERVICE", "iris").strip() or "iris"
        self.messages_path = os.getenv(
            "HECATE_EMAIL_MESSAGES_PATH", "/api/email/messages").strip() or "/api/email/messages"
        self.source_key = os.getenv(
            "HECATE_EMAIL_SOURCE_KEY", "email").strip() or "email"

    def connect(self) -> bool:
        try:
            response = requests.get(
                f"{self.hub_api_url}/registry/services", timeout=5)
            return response.status_code < 400
        except Exception as error:
            logger.warning(
                "event=email_fetcher_connect_failed Email fetcher connect failed: %s", error)
            return False

    def fetch_new_data(self, since_date: datetime, custom_filter: str = "") -> list[dict[str, Any]]:
        query = (custom_filter or "").strip()
        envelope = {
            "method": "GET",
            "headers": {},
            "query": {"q": query, "limit": 100},
            "body": None,
            "timeout_seconds": 10,
        }
        try:
            response = requests.post(
                f"{self.hub_api_url}/route/{self.email_service}/{self.messages_path.lstrip('/')}",
                json=envelope,
                timeout=12,
            )
            response.raise_for_status()
            routed = response.json() if response.content else {}
            if int((routed or {}).get("status_code", 500)) >= 400:
                return []
            payload = (routed or {}).get("payload") or {}
            rows = payload.get("messages") if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                return []
            out: list[dict[str, Any]] = []
            for item in rows:
                if not isinstance(item, dict):
                    continue
                created_at = str(item.get("created_at") or "")
                out.append(
                    {
                        "reference_id": str(item.get("id") or ""),
                        "source": self.source_key,
                        "title": str(item.get("subject") or "No Subject"),
                        "sender": str(item.get("from") or item.get("to") or "Unknown Sender"),
                        "body": str(item.get("body") or ""),
                        "timestamp": created_at,
                    }
                )
            return out
        except Exception as error:
            logger.warning(
                "event=email_fetcher_request_failed Email fetcher request failed: %s", error)
            return []

    def disconnect(self) -> None:
        return

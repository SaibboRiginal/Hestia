import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger("hestia_ingest.archive_client")

# INGEST_ARCHIVE_ROUTE_TIMEOUT: seconds to wait for Hub-routed Archive writes (default 8)
_ROUTE_TIMEOUT = int(os.getenv("INGEST_ARCHIVE_ROUTE_TIMEOUT", "8"))
# INGEST_CALENDAR_WRITE_TIMEOUT: seconds to wait for calendar item writes to Archive (default 10)
_CALENDAR_TIMEOUT = int(os.getenv("INGEST_CALENDAR_WRITE_TIMEOUT", "10"))


class ArchiveClient:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self.archive_base_url = os.getenv(
            "ARCHIVE_URL", "http://hestia_archive:19002")

    def _route_archive(self, payload: dict) -> bool:
        try:
            response = requests.post(
                f"{self.hub_api_url}/route/archive/api/archive",
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": payload,
                    "timeout_seconds": _ROUTE_TIMEOUT,
                },
                timeout=_ROUTE_TIMEOUT + 2,
            )
        except Exception as exc:
            logger.warning("Hub route request failed: %s", exc)
            return False
        if response.status_code != 200:
            logger.warning("Hub returned non-200 | status=%s",
                           response.status_code)
            return False
        routed = response.json() or {}
        return int(routed.get("status_code", 500)) < 400

    def ship_record(self, payload: dict, domain: str, source: str, reference_id: str = None) -> bool:
        """Sends the raw data to the Vault, including the duplicate-protection fingerprint."""

        data = {
            "reference_id": reference_id,
            "domain": domain,
            "source": source,
            "payload": payload
        }

        try:
            if self._route_archive(data):
                logger.debug(
                    "Record shipped via Hub | domain=%s source=%s", domain, source)
                return True

            response = requests.post(self.api_url, json=data)
            if response.status_code == 200:
                logger.debug(
                    "Record shipped via direct URL | domain=%s source=%s", domain, source)
                return True
            logger.warning("Archive rejected record | domain=%s source=%s status=%s",
                           domain, source, response.text[:200])
            return False
        except Exception as e:
            logger.error(
                "Failed to ship to Vault | domain=%s source=%s error=%s", domain, source, e)
            return False

    def ship_calendar_item(self, item: dict[str, Any]) -> bool:
        """Upsert a calendar event / task / reminder into Archive's calendar store.

        ``item`` must be a CalendarItemCreate-compatible dict with at minimum
        ``source``, ``title``, and ``start_at``.  When ``external_id`` is
        provided Archive will update an existing row instead of inserting a
        duplicate.
        """
        try:
            resp = requests.post(
                f"{self.archive_base_url.rstrip('/')}/api/calendar/items",
                json=item,
                timeout=_CALENDAR_TIMEOUT,
            )
            if resp.status_code < 300:
                logger.debug("Calendar item archived | title=%s",
                             item.get('title', '?'))
                return True
            logger.warning("Archive rejected calendar item | title=%s status=%s body=%s",
                           item.get('title', '?'), resp.status_code, resp.text[:200])
            return False
        except Exception as exc:
            logger.error("Failed to archive calendar item | title=%s error=%s", item.get(
                'title', '?'), exc)
            return False

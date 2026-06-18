import logging
import os
from typing import Any, Optional

import requests

logger = logging.getLogger("hestia_hecate.archive_client")

# HECATE_ARCHIVE_ROUTE_TIMEOUT: seconds to wait for Hub-routed Archive writes (default 8)
_ROUTE_TIMEOUT = int(os.getenv("HECATE_ARCHIVE_ROUTE_TIMEOUT", "8"))
# HECATE_CALENDAR_WRITE_TIMEOUT: seconds to wait for calendar item writes to Archive (default 10)
_CALENDAR_TIMEOUT = int(os.getenv("HECATE_CALENDAR_WRITE_TIMEOUT", "10"))


class ArchiveClient:
    def __init__(self):
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

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
            logger.warning(
                "event=hub_route_request_failed Hub route request failed: %s", exc)
            return False
        if response.status_code != 200:
            logger.warning("event=hub_returned_non_status Hub returned non-200 | status=%s",
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
                    "event=record_shipped_hub_domain_source Record shipped via Hub | domain=%s source=%s", domain, source)
                return True
            logger.warning("event=archive_rejected_record_domain_source Archive rejected record via Hub | domain=%s source=%s",
                           domain, source)
            return False
        except Exception as e:
            logger.error(
                "event=failed_ship_vault_domain_source Failed to ship to Vault | domain=%s source=%s error=%s", domain, source, e)
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
                f"{self.hub_api_url}/route/archive/api/calendar/items",
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": item,
                    "timeout_seconds": _CALENDAR_TIMEOUT,
                },
                timeout=_CALENDAR_TIMEOUT + 2,
            )
            if resp.status_code != 200:
                logger.warning("event=archive_rejected_calendar_item_title Archive rejected calendar item | title=%s status=%s body=%s",
                               item.get('title', '?'), resp.status_code, resp.text[:200])
                return False
            routed = resp.json() if resp.content else {}
            if int(routed.get("status_code", 500)) >= 400:
                logger.warning("event=archive_rejected_calendar_item_title Archive rejected calendar item | title=%s routed_status=%s",
                               item.get('title', '?'), routed.get("status_code"))
                return False
            logger.debug("event=calendar_item_archived_title Calendar item archived | title=%s",
                         item.get('title', '?'))
            return True
        except Exception as exc:
            logger.error("event=failed_archive_calendar_item_title Failed to archive calendar item | title=%s error=%s", item.get(
                'title', '?'), exc)
            return False

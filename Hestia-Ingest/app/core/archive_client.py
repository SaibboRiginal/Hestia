import requests
import os
from typing import Any, Optional


class ArchiveClient:
    def __init__(self, api_url: str):
        self.api_url = api_url
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self.archive_base_url = os.getenv(
            "ARCHIVE_URL", "http://hestia_archive:19002")

    def _route_archive(self, payload: dict) -> bool:
        response = requests.post(
            f"{self.hub_api_url}/route/archive/api/archive",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": payload,
                "timeout_seconds": 8,
            },
            timeout=9,
        )
        if response.status_code != 200:
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
                print(f"[✓] Vault saved raw record safely.")
                return True

            response = requests.post(self.api_url, json=data)
            if response.status_code == 200:
                print(f"[✓] Vault saved raw record safely.")
                return True
            print(f"[!] Vault rejected record: {response.text}")
            return False
        except Exception as e:
            print(f"[-] Failed to ship to Vault: {e}")
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
                timeout=10,
            )
            if resp.status_code < 300:
                print(f"[✓] Calendar item archived: {item.get('title', '?')}")
                return True
            print(f"[!] Archive rejected calendar item: {resp.text[:200]}")
            return False
        except Exception as exc:
            print(f"[-] Failed to archive calendar item: {exc}")
            return False

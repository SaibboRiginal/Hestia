import os
from typing import Any
import logging

import requests


logger = logging.getLogger("hestia_hermes.archive")


class ArchiveClient:
    def __init__(self):
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
        self.base_url = os.getenv(
            "ARCHIVE_API_URL", "http://hestia_archive:19002/api").rstrip("/")

    def _route_archive(self, method: str, endpoint: str, body=None, query=None, timeout: int = 8):
        normalized = endpoint.lstrip("/")
        response = requests.post(
            f"{self.hub_api_url}/route/archive/{normalized}",
            json={
                "method": method.upper(),
                "headers": {},
                "query": query or {},
                "body": body,
                "timeout_seconds": timeout,
            },
            timeout=timeout + 1,
        )
        if response.status_code != 200:
            logger.warning(
                "Archive route call failed | endpoint=%s status=%s body=%s",
                endpoint,
                response.status_code,
                response.text[:250],
            )
            return None
        routed = response.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            logger.warning(
                "Archive route returned non-success | endpoint=%s routed_status=%s payload=%s",
                endpoint,
                routed.get("status_code"),
                str(routed.get("payload"))[:250],
            )
            return None
        return routed.get("payload")

    def get_active_subscriptions(self, domain: str, event_type: str) -> list[dict[str, Any]]:
        try:
            payload = self._route_archive(
                "GET",
                "api/subscriptions/active",
                query={"domain": domain, "event_type": event_type},
                timeout=8,
            )
            if isinstance(payload, list):
                return payload
        except Exception as error:
            logger.warning(
                "Archive route exception for subscriptions | domain=%s event_type=%s error=%s",
                domain,
                event_type,
                error,
            )

        endpoint = f"{self.base_url}/subscriptions/active"
        response = requests.get(
            endpoint, params={"domain": domain, "event_type": event_type}, timeout=8)
        if response.status_code != 200:
            logger.warning(
                "Archive direct subscriptions failed | endpoint=%s status=%s body=%s",
                endpoint,
                response.status_code,
                response.text[:250],
            )
            return []
        return response.json() or []

    def write_dispatch_log(self, payload: dict[str, Any]):
        try:
            routed = self._route_archive(
                "POST", "api/dispatch/logs", body=payload, timeout=8)
            if routed is not None:
                return
        except Exception as error:
            logger.warning(
                "Archive route exception for dispatch log | error=%s", error)

        endpoint = f"{self.base_url}/dispatch/logs"
        try:
            response = requests.post(endpoint, json=payload, timeout=8)
            if response.status_code >= 400:
                logger.warning(
                    "Archive direct dispatch log failed | status=%s body=%s",
                    response.status_code,
                    response.text[:250],
                )
        except Exception as error:
            logger.warning(
                "Archive direct dispatch log exception | error=%s", error)
            return

    def find_entity(self, domain: str, entity_id: str) -> dict[str, Any] | None:
        endpoint = f"{self.base_url}/entities/records"
        response = requests.get(
            endpoint, params={"domain": domain, "limit": 2000}, timeout=8)
        if response.status_code != 200:
            return None

        records = response.json() or []
        for record in records:
            if str(record.get("entity_id")) == str(entity_id):
                return record
        return None

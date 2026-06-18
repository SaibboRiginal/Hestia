import os
from typing import Any
import logging

import requests


logger = logging.getLogger("hestia_hermes.archive")


class ArchiveClient:
    def __init__(self):
        self.hub_api_url = os.getenv(
            "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")

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
                "event=archive_route_call_failed_endpoint Archive route call failed | endpoint=%s status=%s body=%s",
                endpoint,
                response.status_code,
                response.text[:250],
            )
            return None
        routed = response.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            logger.warning(
                "event=archive_route_returned_non_success Archive route returned non-success | endpoint=%s routed_status=%s payload=%s",
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
                "event=archive_route_exception_subscriptions_domain Archive route exception for subscriptions | domain=%s event_type=%s error=%s",
                domain,
                event_type,
                error,
            )
        return []

    def write_dispatch_log(self, payload: dict[str, Any]):
        try:
            self._route_archive(
                "POST", "api/dispatch/logs", body=payload, timeout=8)
        except Exception as error:
            logger.warning(
                "event=archive_route_exception_dispatch_log Archive route exception for dispatch log | error=%s", error)

    def find_entity(self, domain: str, entity_id: str) -> dict[str, Any] | None:
        try:
            records = self._route_archive(
                "GET",
                "api/entities/records",
                query={"domain": domain, "limit": 2000},
                timeout=8,
            )
            if isinstance(records, list):
                for record in records:
                    if str(record.get("entity_id")) == str(entity_id):
                        return record
        except Exception as error:
            logger.warning(
                "event=archive_route_exception_find_entity Archive route exception for find_entity | domain=%s entity_id=%s error=%s",
                domain,
                entity_id,
                error,
            )
        return None

    def upsert_outbound_event(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            routed = self._route_archive(
                "POST", "api/outbound-events/upsert", body=payload, timeout=8)
            if isinstance(routed, dict):
                return routed
        except Exception as error:
            logger.warning(
                "event=archive_route_exception_outbound_upsert Archive route exception for outbound upsert | error=%s", error)
        return None

    def get_outbound_events(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            routed = self._route_archive(
                "GET", "api/outbound-events", query=query, timeout=8)
            if isinstance(routed, list):
                return routed
        except Exception as error:
            logger.warning(
                "event=archive_route_exception_outbound_list Archive route exception for outbound list | error=%s", error)
        return []

    def update_outbound_event_state(
        self,
        outbound_event_id: str,
        lifecycle_state: str,
        detail: str | None = None,
        superseded_by: str | None = None,
    ) -> bool:
        body = {
            "lifecycle_state": lifecycle_state,
            "detail": detail,
            "superseded_by": superseded_by,
        }
        endpoint_path = f"api/outbound-events/{outbound_event_id}/state"
        try:
            routed = self._route_archive(
                "PATCH", endpoint_path, body=body, timeout=8)
            if isinstance(routed, dict):
                return True
        except Exception as error:
            logger.warning(
                "event=archive_route_exception_outbound_state Archive route exception for outbound state update | error=%s", error)
        return False

    def find_active_outbound_event(self, dedupe_key: str) -> dict[str, Any] | None:
        rows = self.get_outbound_events(
            {"dedupe_key": dedupe_key, "limit": 20})
        active_states = {"created", "queued", "delivered", "seen", "answered"}
        for row in rows:
            state = str(row.get("lifecycle_state", "")).strip().lower()
            if state in active_states:
                return row
        return None

"""Typed HTTP client for Archive API routed through Hestia Hub.

Single responsibility: all communication to Archive goes through this class.
Oracle never calls Archive directly — every request is routed via Hub's
POST /route/archive/{endpoint} envelope.
"""
import logging
from urllib.parse import urlparse, parse_qs
from typing import Any

import requests

logger = logging.getLogger(f"hestia_oracle.{__name__}")

_ROUTE_PREFIX = "/route/archive/"


class HubClient:
    """Thin wrapper around the Hub routing envelope for Archive endpoints."""

    def __init__(self, hub_api_url: str) -> None:
        self._base = hub_api_url.rstrip("/")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _route_url(self, normalized_endpoint: str) -> str:
        """Build the full Hub routing URL for a given normalized Archive endpoint."""
        return f"{self._base}{_ROUTE_PREFIX}{normalized_endpoint}"

    @staticmethod
    def _normalize(endpoint: str) -> str:
        """Ensure endpoint starts with 'api/' regardless of how it was passed."""
        clean = endpoint.lstrip("/")
        return f"api/{clean}" if not clean.startswith("api/") else clean

    # ── Public API ────────────────────────────────────────────────────────────

    def get(self, endpoint: str, default=None):
        """Route a GET request to Archive via Hub. Returns payload or *default*."""
        try:
            parsed = urlparse(endpoint)
            path = parsed.path if parsed.path.startswith(
                "/") else f"/{parsed.path}"
            query = {
                k: v[0] if len(v) == 1 else v
                for k, v in parse_qs(parsed.query).items()
            }
            url = self._route_url(self._normalize(path))
            resp = requests.post(
                url,
                json={"method": "GET", "query": query, "headers": {},
                      "body": None, "timeout_seconds": 6},
                timeout=7,
            )
            if resp.status_code != 200:
                return default if default is not None else []
            routed = resp.json() or {}
            if int(routed.get("status_code", 500)) < 400:
                return routed.get("payload")
            return default if default is not None else []
        except Exception as exc:
            logger.debug(
                "event=hubclient_get_failed_non_fatal [HubClient] GET %s failed (non-fatal): %s", endpoint, exc)
            return default if default is not None else []

    def post(self, endpoint: str, body: dict, timeout: int = 6):
        """Route a POST request to Archive via Hub. Raises on HTTP error."""
        url = self._route_url(self._normalize(endpoint))
        resp = requests.post(
            url,
            json={"method": "POST", "query": {}, "headers": {},
                  "body": body, "timeout_seconds": timeout},
            timeout=timeout + 1,
        )
        resp.raise_for_status()
        return resp.json() or {}

    def delete(self, endpoint: str, timeout: int = 6):
        """Route a DELETE request to Archive via Hub. Raises on HTTP or Archive error."""
        url = self._route_url(self._normalize(endpoint))
        resp = requests.post(
            url,
            json={"method": "DELETE", "query": {}, "headers": {},
                  "body": None, "timeout_seconds": timeout},
            timeout=timeout + 1,
        )
        resp.raise_for_status()
        routed = resp.json() or {}
        if int(routed.get("status_code", 500)) >= 400:
            raise RuntimeError(routed.get("payload", "delete failed"))
        return routed.get("payload")

    def get_commands(self, client: str = "") -> list[dict]:
        """Fetch all registered service commands from Hub discovery endpoint."""
        try:
            url = f"{self._base}/discovery/commands"
            if client:
                url += f"?client={client}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("commands") or []
        except Exception as exc:
            logger.debug("event=hubclient_get_commands_failed [HubClient] get_commands failed: %s", exc)
        return []

    def route_to_service(
        self,
        service: str,
        path: str,
        method: str,
        body: dict | None = None,
        query: dict | None = None,
        timeout: int = 15,
    ) -> tuple[bool, object]:
        """Route a request to any registered service via Hub routing envelope."""
        clean_path = path.lstrip("/")
        try:
            resp = requests.post(
                f"{self._base}/route/{service}/{clean_path}",
                json={
                    "method": method.upper(),
                    "query": query or {},
                    "headers": {},
                    "body": body,
                    "timeout_seconds": timeout,
                },
                timeout=timeout + 2,
            )
            if resp.status_code != 200:
                return False, resp.text
            routed = resp.json() or {}
            status = int(routed.get("status_code", 500))
            if status >= 400:
                return False, routed.get("payload")
            return True, routed.get("payload")
        except Exception as exc:
            logger.debug(
                "event=hubclient_route_to_service_failed [HubClient] route_to_service %s/%s failed: %s", service, path, exc)
            return False, str(exc)

    def get_history(self, session_id: str, limit: int = 200) -> list[dict]:
        """Fetch raw history list (untruncated) for a session from Archive via Hub.

        Used by background compaction — fetches more than the hot-path limit
        to assess whether compaction is actually warranted.
        """
        result = self.get(f"/chat/history/{session_id}?limit={limit}")
        if isinstance(result, list):
            return result
        return []

    def append_interaction_ledger(
        self,
        *,
        event_type: str,
        session_id: str | None = None,
        actor: str = "assistant",
        domain: str = "general",
        source_service: str = "oracle",
        reference_id: str | None = None,
        payload: dict[str, Any] | None = None,
        timeout: int = 6,
    ) -> dict | None:
        """Append a typed interaction event to Archive's interaction ledger."""
        body = {
            "session_id": session_id,
            "actor": actor,
            "event_type": event_type,
            "domain": domain,
            "source_service": source_service,
            "reference_id": reference_id,
            "payload": payload or {},
        }
        try:
            routed = self.post("/interaction-ledger", body, timeout=timeout)
            if not isinstance(routed, dict):
                return None
            if int(routed.get("status_code", 500)) >= 400:
                return None
            out = routed.get("payload")
            return out if isinstance(out, dict) else None
        except Exception as exc:
            logger.debug(
                "event=hubclient_append_interaction_ledger_failed [HubClient] append_interaction_ledger failed: %s", exc)
            return None

    def create_feedback_record(
        self,
        body: dict[str, Any],
        timeout: int = 6,
    ) -> dict | None:
        """Create a feedback record in Archive via Hub routing."""
        try:
            routed = self.post("/feedback", body, timeout=timeout)
            if not isinstance(routed, dict):
                return None
            if int(routed.get("status_code", 500)) >= 400:
                return None
            out = routed.get("payload")
            return out if isinstance(out, dict) else None
        except Exception as exc:
            logger.debug("event=hubclient_create_feedback_record_failed [HubClient] create_feedback_record failed: %s", exc)
            return None

    def list_feedback_records(
        self,
        *,
        session_id: str | None = None,
        quality_label: str | None = None,
        source_client: str | None = None,
        source_service: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Fetch feedback records from Archive via Hub routing."""
        query_parts: list[str] = [f"limit={max(1, min(limit, 5000))}"]
        if session_id:
            query_parts.append(f"session_id={session_id}")
        if quality_label:
            query_parts.append(f"quality_label={quality_label}")
        if source_client:
            query_parts.append(f"source_client={source_client}")
        if source_service:
            query_parts.append(f"source_service={source_service}")
        result = self.get(f"/feedback?{'&'.join(query_parts)}", default=[])
        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]
        return []

    def export_feedback_jsonl(
        self,
        *,
        session_id: str | None = None,
        quality_label: str | None = None,
        source_client: str | None = None,
        source_service: str | None = None,
        limit: int = 1000,
    ) -> str:
        """Build JSONL text from filtered feedback records."""
        rows = self.list_feedback_records(
            session_id=session_id,
            quality_label=quality_label,
            source_client=source_client,
            source_service=source_service,
            limit=limit,
        )
        lines: list[str] = []
        import json
        for row in rows:
            lines.append(json.dumps(row, ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")

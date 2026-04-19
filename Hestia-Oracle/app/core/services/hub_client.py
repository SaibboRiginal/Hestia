"""Typed HTTP client for Archive API routed through Hestia Hub.

Single responsibility: all communication to Archive goes through this class.
Oracle never calls Archive directly — every request is routed via Hub's
POST /route/archive/{endpoint} envelope.
"""
import logging
from urllib.parse import urlparse, parse_qs

import requests

logger = logging.getLogger(__name__)

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
                "[HubClient] GET %s failed (non-fatal): %s", endpoint, exc)
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

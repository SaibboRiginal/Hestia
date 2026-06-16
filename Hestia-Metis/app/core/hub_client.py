"""Typed HTTP client for Hub-routed Archive and Oracle calls.

Metis reads feedback records from Archive and optionally calls Oracle
for benchmark evaluation — all routed through Hub.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger("hestia_metis.hub_client")

_DEFAULT_TIMEOUT = 12


class HubClient:
    """Thin wrapper around Hub routing for Archive and Oracle endpoints."""

    def __init__(self, hub_api_url: str) -> None:
        self._base = hub_api_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "Hestia-Metis/1.0",
        })

    # ── Public API ─────────────────────────────────────────────────────────

    def fetch_feedback(
        self,
        quality_label: str | None = None,
        min_score: int | None = None,
        limit: int = 500,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Pull graded feedback records from Archive."""
        query_parts = [f"limit={max(1, min(limit, 5000))}"]
        if quality_label:
            query_parts.append(f"quality_label={quality_label}")
        if since:
            query_parts.append(f"since={since}")
        query = "&".join(query_parts)
        return self._route_get(f"archive/api/feedback?{query}")

    def fetch_chat_history(
        self, session_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Pull chat history for a session from Archive."""
        rows = self._route_get(
            f"archive/api/chat/history/{session_id}?limit={limit}"
        )
        if isinstance(rows, list):
            return rows
        if isinstance(rows, dict) and isinstance(rows.get("history"), list):
            return rows["history"]
        return []

    def call_oracle_llm(
        self, prompt: str, model: str = "", provider: str = "", timeout: int = 60
    ) -> str:
        """Call Oracle's LLM generate endpoint for benchmark evaluation."""
        body = {"prompt": prompt, "model": model, "provider": provider}
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": body,
            "timeout_seconds": timeout,
        }
        route_url = f"{self._base}/route/oracle/api/llm/generate"
        try:
            resp = self._session.post(
                route_url, json=envelope, timeout=timeout + 4
            )
            if resp.status_code != 200:
                logger.warning(
                    "event=metis_oracle_call_failed status=%s", resp.status_code
                )
                return ""
            routed = resp.json() if resp.content else {}
            return (routed or {}).get("payload", {}).get("response", "")
        except Exception as exc:
            logger.warning("event=metis_oracle_call_exception error=%s", exc)
            return ""

    # ── Private helpers ────────────────────────────────────────────────────

    def _route_get(self, path: str) -> Any:
        """GET via Hub routing envelope."""
        route_url = f"{self._base}/route/{path.lstrip('/')}"
        envelope = {
            "method": "GET",
            "headers": {},
            "query": {},
            "body": None,
            "timeout_seconds": _DEFAULT_TIMEOUT,
        }
        try:
            resp = self._session.post(
                route_url, json=envelope, timeout=_DEFAULT_TIMEOUT + 4
            )
            if resp.status_code != 200:
                logger.warning(
                    "event=metis_route_get_failed status=%s path=%s",
                    resp.status_code, path,
                )
                return []
            routed = resp.json() if resp.content else {}
            return (routed or {}).get("payload", {})
        except Exception as exc:
            logger.warning(
                "event=metis_route_get_exception path=%s error=%s", path, exc
            )
            return []

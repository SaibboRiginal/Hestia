"""Oracle client for Hermes — narrate batched entity events via Oracle LLM."""
from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger("hestia_hermes.oracle")

_HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
_SESSION_ID = "hermes-narration"


def narrate(prompt: str) -> str:
    """Send a prompt to Oracle and return the reply text.

    Returns an empty string if Oracle is unreachable or returns an error.
    """
    try:
        resp = requests.post(
            f"{_HUB_API_URL}/route/oracle/api/chat",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": {
                    "message": prompt,
                    "session_id": _SESSION_ID,
                    "save_history": False,
                },
                "timeout_seconds": 60,
            },
            timeout=62,
        )
        if resp.status_code >= 400:
            logger.warning(
                "event=oracle_narration_returned_status Oracle narration returned status %s", resp.status_code)
            return ""
        routed = resp.json() if resp.content else {}
        payload = routed.get("payload") if isinstance(routed, dict) else {}
        # Payload may be raw text (NDJSON wrapped in {"raw": "..."})
        raw_text = ""
        if isinstance(payload, dict) and "raw" in payload:
            raw_text = payload["raw"]
        elif isinstance(payload, str):
            raw_text = payload
        # Oracle streams NDJSON — iterate lines to find the "final" event
        for line in raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "final":
                    return str(obj.get("reply", "")).strip()
            except json.JSONDecodeError:
                continue
        return ""
    except Exception as exc:
        logger.warning("event=oracle_narration_failed Oracle narration failed: %s", exc)
        return ""

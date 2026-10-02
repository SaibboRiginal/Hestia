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
    """Ask Oracle to write a message from *prompt*; "" if Oracle fails.

    Uses the plain generation endpoint: narration needs no classifier, tools
    or chat history (the full /api/chat pipeline was slow and burned context).
    """
    try:
        resp = requests.post(
            f"{_HUB_API_URL}/route/oracle/api/llm/generate",
            json={"method": "POST", "headers": {}, "query": {},
                  "body": {"prompt": prompt}, "timeout_seconds": 60},
            timeout=62,
        )
        if resp.status_code >= 400:
            logger.warning(
                "event=oracle_narration_returned_status Oracle narration returned status %s", resp.status_code)
            return ""
        routed = resp.json() if resp.content else {}
        if int((routed or {}).get("status_code", 500)) >= 400:
            logger.warning("event=oracle_narration_non_success status=%s", routed.get("status_code"))
            return ""
        payload = routed.get("payload") if isinstance(routed, dict) else {}
        if isinstance(payload, dict):
            return str(payload.get("response") or "").strip()
        return str(payload or "").strip()
    except Exception as exc:
        logger.warning("event=oracle_narration_failed Oracle narration failed: %s", exc)
        return ""

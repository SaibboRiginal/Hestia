"""Oracle client for Hermes — narrate batched entity events via Oracle LLM."""
from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger("hestia_hermes.oracle")

_ORACLE_URL = os.getenv(
    "ORACLE_API_URL", "http://hestia_oracle:19004/api/chat")
_SESSION_ID = "hermes-narration"


def narrate(prompt: str) -> str:
    """Send a prompt to Oracle and return the reply text.

    Returns an empty string if Oracle is unreachable or returns an error.
    """
    try:
        resp = requests.post(
            _ORACLE_URL,
            json={
                "message": prompt,
                "session_id": _SESSION_ID,
                "save_history": False,
            },
            timeout=60,
        )
        if resp.status_code >= 400:
            logger.warning(
                "Oracle narration returned status %s", resp.status_code)
            return ""
        # Oracle streams NDJSON — iterate lines to find the "final" event
        for line in resp.text.splitlines():
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
        logger.warning("Oracle narration failed: %s", exc)
        return ""

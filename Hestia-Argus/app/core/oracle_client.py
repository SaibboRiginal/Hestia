"""Oracle client — LLM analysis calls routed through Hestia-Oracle.

Argus uses Oracle exclusively for *analysis* (not for plain alerts, which go
directly through Hermes).  The project context loaded by ``context_loader`` is
injected as ``client_instructions`` so Oracle understands what each Hestia
service is supposed to do when it interprets health and log data.
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

ORACLE_URL = os.getenv(
    "ORACLE_API_URL", "http://hestia_oracle:19004/api/chat"
)
ORACLE_SESSION_ID = "argus-analysis"


def analyze(prompt: str, context: str = "") -> str:
    """Send a prompt to Oracle for LLM analysis and return the reply text.

    ``context`` is injected as ``client_instructions`` — Oracle prepends it to
    the system prompt so the model has full awareness of the Hestia ecosystem
    before evaluating the supplied data.

    Returns an empty string if Oracle is unreachable or returns an error.
    """
    instructions = context.strip() if context else ""
    if instructions:
        # Prefix with a framing line so Oracle treats it as background knowledge.
        instructions = (
            "You are the monitoring intelligence for the Hestia home-automation "
            "platform. The following documentation describes each service and its "
            "role. Use it to give informed, actionable analysis.\n\n"
            + instructions
        )

    payload: dict = {
        "message": prompt,
        "session_id": ORACLE_SESSION_ID,
    }
    if instructions:
        payload["client_instructions"] = instructions

    try:
        resp = requests.post(ORACLE_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get("reply", "")
    except Exception as exc:
        logger.warning("Oracle analysis call failed: %s", exc)
        return ""

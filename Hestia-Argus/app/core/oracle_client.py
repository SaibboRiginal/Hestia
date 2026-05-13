"""Oracle client — LLM analysis calls routed through Hestia-Oracle.

Argus uses Oracle exclusively for *analysis* (not for plain alerts, which go
directly through Hermes).  The project context loaded by ``context_loader`` is
injected as ``client_instructions`` so Oracle understands what each Hestia
service is supposed to do when it interprets health and log data.
"""
from __future__ import annotations

import json
import logging
import os

import requests

logger = logging.getLogger(f"hestia_argus.{__name__}")

HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
ORACLE_ROUTE_PATH = os.getenv("ORACLE_ROUTE_PATH", "api/chat").strip("/")
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
        "save_history": False,
    }
    if instructions:
        payload["client_instructions"] = instructions

    try:
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": payload,
            "timeout_seconds": 60,
        }
        resp = requests.post(
            f"{HUB_API_URL}/route/oracle/{ORACLE_ROUTE_PATH}",
            json=envelope,
            timeout=65,
        )
        resp.raise_for_status()
        routed = resp.json() if resp.content else {}
        status_code = int((routed or {}).get("status_code", 500))
        if status_code >= 400:
            logger.warning(
                "event=oracle_analysis_route_non_success Oracle routed call non-success status: %s",
                status_code,
            )
            return ""

        inner_payload = (routed or {}).get("payload") or {}
        raw = ""
        if isinstance(inner_payload, dict):
            raw = str(inner_payload.get("raw") or "")
        if not raw:
            raw = json.dumps(inner_payload)

        # Oracle streams NDJSON — iterate lines to find the "final" event.
        for line in raw.splitlines():
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
        logger.warning(
            "event=oracle_analysis_call_failed Oracle analysis call failed: %s", exc)
        return ""

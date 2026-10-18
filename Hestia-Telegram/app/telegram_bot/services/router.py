"""Pure HTTP routing helpers — no bot interactions, no I/O side effects.

Provides the two core routing primitives used by both the calendar wizard
and the command executor, plus argument parsing and template resolution.
"""
from __future__ import annotations

import re
import logging
from typing import Any

import requests

from telegram_bot import core
from hestia_common.tool_call import build_request, resolve

logger = logging.getLogger("hestia_telegram.router")

# ── Argument helpers ──────────────────────────────────────────────────────────


def parse_command_arguments(raw_text: str) -> dict[str, Any]:
    """Parse ``key=value`` tokens from raw command argument text."""
    parsed: dict[str, Any] = {}
    for token in str(raw_text or "").strip().split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if not normalized_key:
            continue
        parsed[normalized_key] = int(
            normalized_value) if normalized_value.isdigit() else normalized_value
    return parsed


def extract_required_args(arguments_help: str) -> list[str]:
    """Extract argument names from an arguments_help string like ``id=<id>``."""
    if not arguments_help:
        return []
    return [m.group(1).strip().lower() for m in re.finditer(r"([a-zA-Z0-9_]+)\s*=", arguments_help)]


# ── Template resolution ───────────────────────────────────────────────────────

def resolve_template(value: Any, session_id: str, chat_id: int, parsed_args: dict[str, Any]) -> Any:
    """``$session_id``, ``$chat_id`` and ``$arg.*`` placeholders — the shared rules of ``hestia_common.tool_call``."""
    return resolve(value, parsed_args, {"session_id": session_id, "notify_target": str(chat_id)})


# ── Hub routing ───────────────────────────────────────────────────────────────

def route_service_command(
    service: str,
    path: str,
    method: str,
    query: dict[str, Any],
    body: dict[str, Any],
) -> tuple[bool, Any]:
    """Send a command to *service* via the Hub routing envelope.

    Returns ``(True, payload)`` on success or ``(False, error_detail)`` on failure.
    """
    normalized_path = str(path or "").lstrip("/")
    try:
        response = requests.post(
            f"{core.HUB_API_URL}/route/{service}/{normalized_path}",
            json={
                "method": str(method or "GET").upper(),
                "headers": {},
                "query": query or {},
                "body": body,
                "timeout_seconds": 25,
            },
            timeout=30,
        )
        if response.status_code != 200:
            logger.warning(
                "event=route_envelope_request_failed_service Route envelope request failed | service=%s method=%s path=%s status=%s",
                service,
                method,
                normalized_path,
                response.status_code,
            )
            return False, response.text

        routed = response.json() or {}
        status_code = int(routed.get("status_code", 500))
        payload = routed.get("payload")
        if status_code >= 400:
            logger.warning(
                "event=routed_service_returned_error_service Routed service returned error | service=%s method=%s path=%s status=%s",
                service,
                method,
                normalized_path,
                status_code,
            )
            return False, payload
        return True, payload
    except Exception as error:
        logger.warning(
            "event=route_exception_service_method_path Route exception | service=%s method=%s path=%s error=%s",
            service,
            method,
            normalized_path,
            error,
        )
        return False, str(error)


def route_command_from_metadata(
    command_meta: dict[str, Any],
    chat_id: int,
    parsed_args: dict[str, Any],
) -> tuple[bool, Any]:
    """Run a tool through Hestia-MCP (the one way, docs/work/2026-10-18-moduli-core-e-mcp-esterno).

    ``command_meta`` without a tool name is an ``arg_picker.source`` (a data read declared by a tool):
    the same template rules (``hestia_common.tool_call``) and a plain Hub route."""
    session_id = core.get_session(str(chat_id))
    tool = str(command_meta.get("tool") or "").strip()
    if tool:
        from telegram_bot.services.registry import mcp_client
        return mcp_client().call(tool, parsed_args, session_id=session_id, notify_target=str(chat_id),
                                 service=str(command_meta.get("service", "")), timeout=25)
    req = build_request(command_meta, parsed_args, {"session_id": session_id, "notify_target": str(chat_id)})
    return route_service_command(service=req["service"], path=req["path"], method=req["method"],
                                 query=req["query"], body=req["body"] or {})

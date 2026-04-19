"""Pure HTTP routing helpers — no bot interactions, no I/O side effects.

Provides the two core routing primitives used by both the calendar wizard
and the command executor, plus argument parsing and template resolution.
"""
from __future__ import annotations

import re
from typing import Any

import requests

from telegram_bot import core

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
    """Recursively replace ``$session_id``, ``$chat_id``, and ``$arg.*`` placeholders."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "$session_id":
            return session_id
        if stripped == "$chat_id":
            return str(chat_id)
        if stripped.startswith("$arg."):
            arg_key = stripped.replace("$arg.", "", 1).strip().lower()
            return parsed_args.get(arg_key)

        def _sub(match: re.Match) -> str:
            token = match.group(1)
            if token == "session_id":
                return session_id
            if token == "chat_id":
                return str(chat_id)
            if token.startswith("arg."):
                return str(parsed_args.get(token[4:].strip().lower(), ""))
            return ""

        return re.sub(r"\$(session_id|chat_id|arg\.[a-zA-Z0-9_]+)", _sub, value)

    if isinstance(value, dict):
        resolved: dict[str, Any] = {}
        for k, item in value.items():
            computed = resolve_template(item, session_id, chat_id, parsed_args)
            is_arg_tmpl = isinstance(
                item, str) and item.strip().startswith("$arg.")
            if is_arg_tmpl and (computed is None or computed == ""):
                continue
            if computed is not None:
                resolved[k] = computed
        return resolved

    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            computed = resolve_template(item, session_id, chat_id, parsed_args)
            is_arg_tmpl = isinstance(
                item, str) and item.strip().startswith("$arg.")
            if is_arg_tmpl and (computed is None or computed == ""):
                continue
            if computed is not None:
                out.append(computed)
        return out

    return value


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
                "body": body if body else None,
                "timeout_seconds": 10,
            },
            timeout=12,
        )
        if response.status_code != 200:
            print(
                f"[-] Route failed: service={service} method={method} path={normalized_path} status={response.status_code}")
            return False, response.text

        routed = response.json() or {}
        status_code = int(routed.get("status_code", 500))
        payload = routed.get("payload")
        if status_code >= 400:
            print(
                f"[-] Routed error: service={service} method={method} path={normalized_path} status={status_code}")
            return False, payload
        return True, payload
    except Exception as error:
        print(
            f"[-] Route exception: service={service} method={method} path={normalized_path} error={error}")
        return False, str(error)


def route_command_from_metadata(
    command_meta: dict[str, Any],
    chat_id: int,
    parsed_args: dict[str, Any],
) -> tuple[bool, Any]:
    """Resolve templates from *command_meta* and dispatch via Hub."""
    query_template = command_meta.get("query_template") if isinstance(
        command_meta.get("query_template"), dict) else {}
    body_template = command_meta.get("body_template") if isinstance(
        command_meta.get("body_template"), dict) else {}

    session_id = core.get_session(str(chat_id))
    query = resolve_template(query_template, session_id, chat_id, parsed_args)
    if not isinstance(query, dict):
        query = {}
    query.update(parsed_args)

    body = resolve_template(body_template, session_id, chat_id, parsed_args)
    if not isinstance(body, dict):
        body = {}

    path_value = resolve_template(str(command_meta.get(
        "path", "")).strip(), session_id, chat_id, parsed_args)
    return route_service_command(
        service=str(command_meta.get("service", "")).strip(),
        path=str(path_value or "").strip(),
        method=str(command_meta.get("method", "GET")).upper(),
        query=query,
        body=body,
    )

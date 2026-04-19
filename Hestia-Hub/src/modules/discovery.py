"""Hub discovery helpers.

Single responsibility: aggregate and expose information from the service
registry for tool-routing and command discovery.
"""
from __future__ import annotations

import re

from .registry import ServiceRegistry

_COMMAND_NAME_RE = re.compile(r"[a-z0-9_]{2,32}")


def discover_module_tools(registry: ServiceRegistry) -> dict[str, list[str]]:
    """Return a domain→endpoint-list mapping for every registered module tool."""
    mapping: dict[str, list[str]] = {}

    for service in registry.all_services():
        capabilities = service.get("capabilities") or {}
        domains = capabilities.get("module_tool_domains") or []
        endpoint = capabilities.get("module_tool_endpoint")
        if not endpoint:
            continue

        for domain in domains:
            normalized_domain = str(domain).strip().lower()
            if not normalized_domain:
                continue
            mapping.setdefault(normalized_domain, []).append(
                endpoint.rstrip("/"))

    return mapping


def discover_commands(registry: ServiceRegistry, client_key: str = "") -> list[dict]:
    """Return a deduplicated, sorted list of commands from all registered services.

    Parameters
    ----------
    registry:
        Active :class:`ServiceRegistry` instance.
    client_key:
        Optional client identifier (e.g. ``"telegram"``).  When non-empty, only
        commands whose ``clients`` list includes *client_key* or ``"*"`` are
        returned.  Commands with no ``clients`` restriction are always included.
    """
    discovered_map: dict[tuple[str, str], dict] = {}
    normalized_client = str(client_key or "").strip().lower()

    for service in registry.all_services():
        capabilities = service.get("capabilities") or {}
        commands = capabilities.get("commands") or []
        if not isinstance(commands, list):
            continue

        service_name = str(service.get("name", "")).strip().lower()
        if not service_name:
            continue

        registration_ts = float(service.get("updated_at", 0.0) or 0.0)

        for command in commands:
            if not isinstance(command, dict):
                continue

            name = str(command.get("command", "")).strip().lower()
            if not _COMMAND_NAME_RE.fullmatch(name):
                continue

            raw_clients = command.get("clients")
            clients: list[str] = (
                [str(c).strip().lower() for c in raw_clients if str(c).strip()]
                if isinstance(raw_clients, list) else []
            )
            if normalized_client and clients and normalized_client not in clients and "*" not in clients:
                continue

            key = (service_name, name)
            candidate: dict = {
                "command": name,
                "title": str(command.get("title", command.get("description", name))).strip() or name,
                "description": str(command.get("description", name)).strip() or name,
                "service": service_name,
                "method": str(command.get("method", "GET")).upper(),
                "path": str(command.get("path", "")).strip(),
                "query_template": command.get("query_template") if isinstance(command.get("query_template"), dict) else {},
                "body_template": command.get("body_template") if isinstance(command.get("body_template"), dict) else {},
                "response_mode": str(command.get("response_mode", "raw_json")).strip().lower(),
                "response_prompt": str(command.get("response_prompt", "")).strip(),
                "arguments_help": str(command.get("arguments_help", "")).strip(),
                "arg_picker": command.get("arg_picker") if isinstance(command.get("arg_picker"), dict) else {},
                "telegram_visible": bool(command.get("telegram_visible", False)),
                "telegram_help_visible": bool(command.get("telegram_help_visible", True)),
                "clients": clients,
                "_registration_ts": registration_ts,
            }

            existing = discovered_map.get(key)
            if not existing or candidate["_registration_ts"] >= existing.get("_registration_ts", 0.0):
                discovered_map[key] = candidate

    results = list(discovered_map.values())
    for item in results:
        item.pop("_registration_ts", None)
    results.sort(key=lambda c: (c.get("service", ""), c.get("command", "")))
    return results

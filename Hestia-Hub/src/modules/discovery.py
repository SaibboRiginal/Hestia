"""Hub discovery helpers.

Single responsibility: aggregate and expose information from the service
registry for tool-routing and command discovery.
"""
from __future__ import annotations

import logging
import re
import time

import requests

from .registry import ServiceRegistry

logger = logging.getLogger("hestia_hub.discovery")

_COMMAND_NAME_RE = re.compile(r"[a-z0-9_]{2,64}")

# ── MCP tool → command format mapping ──────────────────────────────────────────
# Cache TTL for MCP tool discovery (seconds).
_MCP_DISCOVERY_CACHE_TTL = 30.0


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


# ── MCP tool discovery cache ───────────────────────────────────────────────────
_mcp_commands_cache: dict[str, tuple[float, list[dict]]] = {}


def _fetch_mcp_tools_as_commands(
    service_name: str,
    mcp_endpoint: str,
    capabilities: dict,
    timeout: float = 5.0,
) -> list[dict]:
    """Fetch MCP tools/list from a service and convert to command format.

    Uses a short-lived in-process cache to avoid hammering services on every
    discovery request.
    """
    cache_key = f"{service_name}:{mcp_endpoint}"
    now = time.time()
    if cache_key in _mcp_commands_cache:
        cached_ts, cached_commands = _mcp_commands_cache[cache_key]
        if now - cached_ts < _MCP_DISCOVERY_CACHE_TTL:
            return cached_commands

    commands: list[dict] = []
    # mcp_endpoint is already the full /mcp URL (e.g. http://host:port/mcp)
    mcp_url = mcp_endpoint.rstrip("/")
    try:
        resp = requests.post(
            mcp_url,
            json={"method": "tools/list", "id": "hub-discovery"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.debug(
                "event=mcp_discovery_non_200 service=%s endpoint=%s status=%s",
                service_name, mcp_endpoint, resp.status_code,
            )
            return commands

        data = resp.json() or {}
        tools = data.get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            return commands

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip().lower()
            if not name:
                continue

            # Build a Hub command from MCP tool metadata.
            # MCP tools carry all Hestia client metadata (title, method, path,
            # clients, response_mode, response_prompt, telegram_visible, etc.)
            # as top-level fields in the tool descriptor.
            cmd: dict = {
                "command": name,
                "title": str(tool.get("title") or tool.get("description") or name).strip() or name,
                "description": str(tool.get("description") or name).strip(),
                "service": service_name,
                "method": str(tool.get("method", "GET")).upper(),
                "path": str(tool.get("path", "")).strip(),
                "query_template": tool.get("query_template") if isinstance(tool.get("query_template"), dict) else {},
                "body_template": tool.get("body_template") if isinstance(tool.get("body_template"), dict) else {},
                "response_mode": str(tool.get("response_mode", "oracle_natural")).strip().lower(),
                "response_prompt": str(tool.get("response_prompt", "")).strip(),
                "arguments_schema": _mcp_input_schema_to_args(tool.get("inputSchema")),
                "clients": _normalize_clients(tool.get("clients")),
                "telegram_visible": bool(tool.get("telegram_visible", False)),
                "telegram_help_visible": bool(tool.get("telegram_help_visible", True)),
                "telegram_group": str(tool.get("telegram_group", "altro")).strip(),
            }
            commands.append(cmd)

        logger.info(
            "event=mcp_tools_discovered service=%s endpoint=%s tool_count=%s",
            service_name, mcp_endpoint, len(commands),
        )
    except Exception as exc:
        logger.debug(
            "event=mcp_discovery_failed service=%s endpoint=%s error=%s",
            service_name, mcp_endpoint, exc,
        )

    _mcp_commands_cache[cache_key] = (now, commands)
    return commands


def _mcp_input_schema_to_args(schema: dict | None) -> dict:
    """Convert a JSON Schema input descriptor to Hub argument_schema format.

    Returns a dict mapping argument name → {type, description, required}.
    """
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required: list[str] = schema.get("required") if isinstance(schema.get("required"), list) else []
    args: dict = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        args[str(prop_name)] = {
            "type": str(prop_schema.get("type", "string")),
            "description": str(prop_schema.get("description", prop_name)),
            "required": str(prop_name) in required,
        }
    return args


def _normalize_clients(raw_clients: list | None) -> list[str]:
    """Normalize a clients list from MCP tool metadata."""
    if not isinstance(raw_clients, list):
        return []
    return [str(c).strip().lower() for c in raw_clients if str(c).strip()]


def _mcp_commands_cache_invalidate(service_name: str | None = None) -> None:
    """Clear the MCP tool discovery cache (used on registry changes)."""
    if service_name:
        keys_to_del = [k for k in _mcp_commands_cache if k.startswith(f"{service_name}:")]
        for k in keys_to_del:
            _mcp_commands_cache.pop(k, None)
    else:
        _mcp_commands_cache.clear()


def discover_commands(registry: ServiceRegistry, client_key: str = "") -> list[dict]:
    """Return a deduplicated, sorted list of commands from all registered services.

    Aggregates commands from two sources:

    1. **Inline commands** — ``capabilities.commands`` in service registration.
    2. **MCP tools** — fetched from services that declare an ``mcp_endpoint`` in
       their capabilities.  Results are cached for a short TTL to avoid
       hammering downstream services.

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

        service_name = str(service.get("name", "")).strip().lower()
        if not service_name:
            continue

        registration_ts = float(service.get("updated_at", 0.0) or 0.0)

        # ── Source 1: Inline commands from capabilities.commands ────────────
        commands = capabilities.get("commands") or []
        if isinstance(commands, list):
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
                    "arguments_schema": command.get("arguments_schema") if isinstance(command.get("arguments_schema"), dict) else {},
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

        # ── Source 2: MCP tools from mcp_endpoint ───────────────────────────
        mcp_endpoint = str(capabilities.get("mcp_endpoint") or "").strip()
        if mcp_endpoint:
            mcp_commands = _fetch_mcp_tools_as_commands(
                service_name=service_name,
                mcp_endpoint=mcp_endpoint,
                capabilities=capabilities,
            )
            for cmd in mcp_commands:
                name = str(cmd.get("command", "")).strip().lower()
                if not name:
                    continue

                raw_clients = cmd.get("clients") or []
                if normalized_client and raw_clients and normalized_client not in raw_clients and "*" not in raw_clients:
                    continue

                key = (service_name, name)
                cmd["_registration_ts"] = registration_ts

                existing = discovered_map.get(key)
                if not existing or registration_ts >= existing.get("_registration_ts", 0.0):
                    discovered_map[key] = cmd

    results = list(discovered_map.values())
    for item in results:
        item.pop("_registration_ts", None)
    results.sort(key=lambda c: (c.get("service", ""), c.get("command", "")))
    return results

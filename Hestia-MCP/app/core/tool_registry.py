"""ToolRegistry — aggregates tools from MCP servers and Hub command discovery.

Phase 8: Discovers tools from both sources. MCP-preferring, Hub-fallback.
During Phase 9 migration, each service switches from Hub → MCP transparently.

Domain filtering: Oracle requests tools for specific domains, and the registry
returns only relevant tools. This keeps LLM manifests small (5-12 tools).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger("hestia_mcp.tool_registry")

_MCP_TOOLS_CACHE_TTL = int(os.getenv("MCP_TOOLS_CACHE_TTL_SECONDS", "60"))
_HUB_DISCOVERY_TIMEOUT = int(os.getenv("MCP_HUB_DISCOVERY_TIMEOUT_SEC", "8"))
_MCP_SERVER_TIMEOUT = int(os.getenv("MCP_SERVER_TIMEOUT_SEC", "10"))


class ToolRegistry:
    """Single source of truth for all tools in the Hestia ecosystem."""

    def __init__(self, hub_api_url: str):
        self._hub_url = hub_api_url.rstrip("/")
        self._cache: dict[str, list[dict]] = {}       # domain → [tools]
        self._cache_ts: dict[str, float] = {}
        self._service_mcp_map: dict[str, str] = {}     # service_name → mcp_endpoint
        self._service_domains: dict[str, list[str]] = {}  # service_name → [domains]

    # ── Public API ──────────────────────────────────────────────────────────

    def get_tools_for_domains(self, domains: list[str]) -> list[dict]:
        """Return all tools relevant to the given domains, with caching."""
        key = ",".join(sorted(set(domains)))
        now = time.time()
        if key in self._cache and (now - self._cache_ts.get(key, 0)) < _MCP_TOOLS_CACHE_TTL:
            return self._cache[key]

        tools: list[dict] = []
        tools.extend(self._get_always_tools())
        tools.extend(self._get_domain_search_tools(domains))
        tools.extend(self._get_service_tools_for_domains(domains))

        # Deduplicate by name
        seen: set[str] = set()
        unique: list[dict] = []
        for t in tools:
            name = t.get("name", "")
            if name and name not in seen:
                seen.add(name)
                unique.append(t)

        self._cache[key] = unique
        self._cache_ts[key] = now
        logger.info(
            "event=tools_resolved domains=%s count=%s",
            ",".join(domains), len(unique),
        )
        return unique

    def list_all_tools(self) -> list[dict]:
        """Return all known tools across ALL MCP services (for Telegram command catalog)."""
        self.refresh()
        tools: list[dict] = []
        tools.extend(self._get_always_tools())
        for svc_name, mcp_ep in self._service_mcp_map.items():
            mcp_tools = self._discover_mcp_tools(svc_name, mcp_ep)
            for t in mcp_tools:
                t["service"] = svc_name
            tools.extend(mcp_tools)
        # Deduplicate by name
        seen: set[str] = set()
        unique: list[dict] = []
        for t in tools:
            name = t.get("name", "")
            if name and name not in seen:
                seen.add(name)
                unique.append(t)
        logger.info("event=tools_list_all count=%d", len(unique))
        return unique

    def call_tool(self, tool_name: str, params: dict, service: str = "") -> tuple[bool, Any]:
        """Execute a tool by routing to its service via Hub."""
        if not service:
            return (False, f"No service specified for tool '{tool_name}'")

        try:
            resp = requests.post(
                f"{self._hub_url}/route/{service}/api/module-tools/call",
                json={"tool": tool_name, "params": params},
                timeout=_MCP_SERVER_TIMEOUT,
            )
            if resp.status_code == 200:
                payload = resp.json()
                return (True, payload.get("payload", payload))
            return (False, f"Service {service} returned {resp.status_code}")
        except Exception as exc:
            logger.warning("event=tool_call_failed tool=%s service=%s error=%s",
                           tool_name, service, exc)
            return (False, str(exc))

    def refresh(self) -> None:
        """Force-refresh the service → MCP endpoint mapping and domain mapping from Hub registry."""
        try:
            resp = requests.get(
                f"{self._hub_url}/registry/services",
                timeout=_HUB_DISCOVERY_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            if isinstance(data, dict):
                services = data.get("services") or []
            else:
                services = data if isinstance(data, list) else []
            if isinstance(services, list):
                for svc in services:
                    if not isinstance(svc, dict):
                        continue
                    name = svc.get("name", "")
                    caps = svc.get("capabilities") or {}
                    mcp_ep = caps.get("mcp_endpoint", "")
                    if name and mcp_ep:
                        self._service_mcp_map[name] = str(mcp_ep)
                        domains = caps.get("module_tool_domains") or []
                        if isinstance(domains, list) and domains:
                            self._service_domains[name] = [str(d).strip().lower() for d in domains]
        except Exception as exc:
            logger.warning("event=registry_refresh_failed error=%s", exc)

    # ── Private helpers ─────────────────────────────────────────────────────

    def _get_always_tools(self) -> list[dict]:
        """Tools that are always available regardless of domain."""
        return [
            {
                "name": "memory.save",
                "description": "Save a durable fact or preference about the user for future reference.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "description": "The durable fact to remember"},
                        "domain": {"type": "string", "description": "Domain category"},
                    },
                    "required": ["fact"],
                },
                "service": "oracle",
            },
            {
                "name": "memory.search",
                "description": "Search saved memories and preferences about the user.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keywords to search for"},
                    },
                },
                "service": "oracle",
            },
            {
                "name": "documents.search",
                "description": "Search through uploaded documents and files for relevant content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for documents"},
                    },
                    "required": ["query"],
                },
                "service": "oracle",
            },
        ]

    def _get_domain_search_tools(self, domains: list[str]) -> list[dict]:
        """Generate {domain}.search tools for each domain."""
        tools = []
        for domain in domains:
            if domain == "general":
                continue
            tools.append({
                "name": f"{domain}.search",
                "description": f"Search {domain} domain entities. Use for queries related to {domain}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query text"},
                        "filters": {"type": "object", "description": "Exact-match field filters"},
                        "filters_gt": {"type": "object", "description": "Greater-than numeric filters"},
                        "filters_lt": {"type": "object", "description": "Less-than numeric filters"},
                        "sort_by": {"type": "string", "description": "Sort field"},
                        "sort_order": {"type": "string", "enum": ["asc", "desc"]},
                    },
                },
                "service": domain,
            })
        return tools

    def _get_service_tools_for_domains(self, domains: list[str]) -> list[dict]:
        """Discover tools from MCP services whose declared domains match the request."""
        tools: list[dict] = []
        self.refresh()
        domain_set = set(str(d).strip().lower() for d in domains)

        for svc_name, mcp_ep in self._service_mcp_map.items():
            svc_domains = self._service_domains.get(svc_name, [])
            if domain_set and not domain_set.intersection(svc_domains):
                continue
            mcp_tools = self._discover_mcp_tools(svc_name, mcp_ep)
            for t in mcp_tools:
                t["service"] = svc_name
            tools.extend(mcp_tools)

        return tools

    def _discover_mcp_tools(self, service_name: str, endpoint: str) -> list[dict]:
        """Call tools/list on an MCP server."""
        try:
            resp = requests.post(
                endpoint,
                json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1},
                timeout=_MCP_SERVER_TIMEOUT,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("result", {}).get("tools", [])
        except Exception as exc:
            logger.debug("event=mcp_discover_failed service=%s error=%s", service_name, exc)
            return []


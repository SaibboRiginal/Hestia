"""Client of Hestia's one MCP server (Hestia-MCP ``/mcp``), through Hub like every service call.

Oracle, Telegram and every Python client list and call tools only through this
(docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2). The WebUI (.NET) speaks the same JSON-RPC.

    mcp = MCPClient(HUB_API_URL, client="telegram")
    tools = mcp.list_tools()                      # MCP tools, Hestia details in tool["_meta"]["hestia"]
    commands = [as_command(t) for t in tools]     # legacy command shape (service, method, path, telegram_*…)
    ok, payload = mcp.call("forge_tasks", {"limit": 5}, session_id=sid, notify_target=chat_id)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

logger = logging.getLogger("hestia_common.mcp_client")

PROTOCOL_VERSION = "2025-06-18"


class MCPClient:
    def __init__(self, hub_api_url: str, client: str, *, cache_ttl: float = 30.0, timeout: float = 30.0):
        self.hub = hub_api_url.rstrip("/")
        self.client = client
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()
        self._id = 0

    def _rpc(self, method: str, params: dict, timeout: float | None = None) -> dict:
        with self._lock:
            self._id += 1
            msg_id = self._id
        wait = float(timeout or self.timeout)
        resp = requests.post(
            f"{self.hub}/route/mcp/mcp",
            json={"method": "POST", "headers": {"X-Hestia-Client": self.client}, "query": {},
                  "body": {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params},
                  "timeout_seconds": wait},
            timeout=wait + 5)
        resp.raise_for_status()
        routed = resp.json() or {}
        payload = routed.get("payload") or {}
        if int(routed.get("status_code", 500)) >= 400 or not isinstance(payload, dict):
            raise RuntimeError(f"mcp returned {routed.get('status_code')}: {str(payload)[:200]}")
        if payload.get("error"):
            raise RuntimeError(str(payload["error"].get("message") or payload["error"]))
        return payload.get("result") or {}

    def list_tools(self, *, services: list[str] | None = None, refresh: bool = False) -> list[dict]:
        """Tools this client may see (cached ``cache_ttl`` s). Empty list when Hestia-MCP is unreachable."""
        key = ",".join(sorted(services or []))
        now = time.time()
        cached = self._cache.get(key)
        if cached and not refresh and now - cached[0] < self.cache_ttl:
            return cached[1]
        meta = {"hestia": {"client": self.client, **({"services": services} if services else {})}}
        try:
            tools: list[dict] = []
            cursor = None
            for _ in range(20):
                params: dict[str, Any] = {"_meta": meta}
                if cursor:
                    params["cursor"] = cursor
                result = self._rpc("tools/list", params)
                tools.extend(t for t in result.get("tools") or [] if isinstance(t, dict))
                cursor = result.get("nextCursor")
                if not cursor:
                    break
        except Exception as exc:  # noqa: BLE001 — clients keep their last list
            logger.warning("[🔄] event=mcp_list_tools_failed client=%s error=%s", self.client, exc)
            return cached[1] if cached else []
        self._cache[key] = (now, tools)
        return tools

    def call(self, name: str, arguments: dict | None = None, *, session_id: str = "", notify_target: str = "",
             trace_id: str = "", service: str = "", origin_client: str = "",
             timeout: float | None = None) -> tuple[bool, Any]:
        """``(ok, payload)``: the module's JSON answer on success, the error detail otherwise.
        ``origin_client`` = the client the user is talking from (webui, telegram), sent to the module as
        ``X-Hestia-Client`` (e.g. Themis answers a chat-born proposal with a confirm card for that client)."""
        hestia = {k: v for k, v in {"session_id": session_id, "notify_target": notify_target, "trace_id": trace_id,
                                    "service": service, "client": origin_client,
                                    "timeout_seconds": timeout}.items() if v}
        try:
            result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}, "_meta": {"hestia": hestia}},
                               timeout=(timeout or self.timeout) + 2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("event=mcp_call_failed client=%s tool=%s error=%s", self.client, name, exc)
            return False, str(exc)
        payload = result.get("structuredContent")
        if payload is None:
            texts = [c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text"]
            payload = "\n".join(texts)
        if isinstance(payload, dict) and hestia_meta(result).get("wrapped"):
            payload = payload.get("result")   # non-object answers are wrapped by the server
        return (not result.get("isError"), payload)


def hestia_meta(tool: dict) -> dict:
    return ((tool.get("_meta") or {}).get("hestia") or {}) if isinstance(tool, dict) else {}


def as_command(tool: dict) -> dict:
    """MCP tool → the command dict clients used before (Hub ``/discovery/commands`` shape)."""
    meta = hestia_meta(tool)
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or [])
    return {
        "command": tool.get("name", ""),
        "title": tool.get("title") or meta.get("title") or tool.get("name", ""),
        "description": tool.get("description", ""),
        "service": meta.get("service", ""),
        "method": meta.get("method", "GET"),
        "path": meta.get("path", ""),
        "arguments_schema": {k: {"type": str((v or {}).get("type", "string")),
                                 "description": str((v or {}).get("description", k)), "required": k in required}
                             for k, v in props.items()},
        "response_mode": meta.get("response_mode", "oracle_natural"),
        "response_prompt": meta.get("response_prompt", ""),
        "arguments_help": meta.get("arguments_help", ""),
        "arg_picker": meta.get("arg_picker") or {},
        "clients": meta.get("clients") or [],
        "telegram_visible": bool(meta.get("telegram_visible", False)),
        "telegram_help_visible": bool(meta.get("telegram_help_visible", True)),
        "telegram_group": meta.get("telegram_group", ""),
        "writes": not bool((tool.get("annotations") or {}).get("readOnlyHint", False)),
    }

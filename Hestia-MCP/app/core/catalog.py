"""The tools Hestia offers, as MCP tools — built from Hub's registry discovery.

Hub knows every module's tools (each module's own ``/mcp`` plus inline ``capabilities.commands``) and exposes them
at ``/discovery/commands``. Hestia-MCP is the only reader: it turns them into MCP tool descriptors and executes
them (``hestia_common.tool_call``), so every client — Oracle, Telegram, WebUI, external AIs — sees the same list
and the same execution rules (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2).
"""
from __future__ import annotations

import logging
import time
import requests

from core.mcp_settings import HUB_DISCOVERY_TIMEOUT, TOOLS_CACHE_TTL, settings

try:
    from hestia_common.tool_call import is_write, template_vars
except ModuleNotFoundError:  # local runs without the shared package on the path
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Hestia-Shared"))
    from hestia_common.tool_call import is_write, template_vars

logger = logging.getLogger("hestia_mcp.catalog")

# Command discovery predates the WebUI name: its commands use the client key "ui".
CLIENT_KEYS = {"webui": "ui"}
_META_KEYS = ("method", "path", "response_mode", "response_prompt", "arguments_help", "arg_picker", "clients",
              "telegram_visible", "telegram_help_visible", "telegram_group", "query_template", "body_template")


def _input_schema(cmd: dict) -> dict:
    args = cmd.get("arguments_schema") if isinstance(cmd.get("arguments_schema"), dict) else {}
    if args:
        props = {k: {"type": str((v or {}).get("type", "string")), "description": str((v or {}).get("description", k))}
                 for k, v in args.items()}
        required = [k for k, v in args.items() if (v or {}).get("required")]
    else:
        names = template_vars(cmd.get("query_template") or {}) | template_vars(cmd.get("body_template") or {}) \
            | template_vars(str(cmd.get("path") or ""))
        props = {n: {"type": "string", "description": n} for n in sorted(names)}
        required = sorted(names)
    return {"type": "object", "properties": props, "required": required}


def to_mcp_tool(cmd: dict) -> dict:
    name = str(cmd.get("command") or "")
    meta = {"service": cmd.get("service", ""), **{k: cmd[k] for k in _META_KEYS if k in cmd and cmd[k] not in (None, "")}}
    title = str(cmd.get("title") or name)
    return {"name": name, "title": title, "description": str(cmd.get("description") or title),
            "inputSchema": _input_schema(cmd),
            "annotations": {"title": title, "readOnlyHint": not is_write(cmd)},
            "_meta": {"hestia": meta}}


EXTERNAL = "external"


def visible_to(cmd: dict, client: str) -> bool:
    """Empty ``clients`` = every client; otherwise the client's key or ``*``. Oracle sees everything.
    External AIs see only tools whose module wrote ``"external"`` explicitly (nothing leaves the house by default)."""
    clients = [str(c).lower() for c in cmd.get("clients") or []]
    if client == EXTERNAL:
        return EXTERNAL in clients
    if not client or client == "oracle":
        return True
    return not clients or "*" in clients or CLIENT_KEYS.get(client, client) in clients or client in clients


class ToolCatalog:
    def __init__(self, hub_api_url: str):
        self._hub = hub_api_url.rstrip("/")
        self._commands: list[dict] = []
        self._ts = 0.0

    def commands(self, refresh: bool = False) -> list[dict]:
        ttl = int(settings.get(TOOLS_CACHE_TTL))
        if not refresh and self._commands and time.time() - self._ts < ttl:
            return self._commands
        try:
            resp = requests.get(f"{self._hub}/discovery/commands", timeout=int(settings.get(HUB_DISCOVERY_TIMEOUT)))
            resp.raise_for_status()
            items = [c for c in (resp.json() or {}).get("commands") or [] if isinstance(c, dict) and c.get("command")]
            self._commands, self._ts = items, time.time()
            logger.info("event=tool_catalog_refreshed count=%d", len(items))
        except Exception as exc:  # noqa: BLE001 — keep serving the last list
            logger.warning("[🔄] event=tool_catalog_refresh_failed kept=%d error=%s", len(self._commands), exc)
        return self._commands

    def tools(self, client: str = "", services: list[str] | None = None) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for cmd in self.commands():
            name = cmd["command"]
            if name in seen or not visible_to(cmd, client):
                continue
            if services and cmd.get("service") not in services:
                continue
            seen.add(name)
            out.append(to_mcp_tool(cmd))
        return out

    def find(self, name: str, service: str = "") -> dict | None:
        for refresh in (False, True):
            for cmd in self.commands(refresh=refresh):
                if cmd["command"] == name and (not service or cmd.get("service") == service):
                    return cmd
        return None

    def count(self) -> int:
        return len(self.commands())


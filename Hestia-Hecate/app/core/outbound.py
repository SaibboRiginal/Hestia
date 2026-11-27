"""Outbound MCP servers: third-party MCP servers Hestia itself may use (docs/work/2026-10-18-core-modules-and-external-mcp
§B3; linked from Connections since docs/work/2026-11-27-connections-leftovers).

Hecate owns external providers, so it owns their credentials too. Each server is linked from the «External MCP
servers» card (page Connections): its name and address are the Themis setting ``hecate.mcp.servers``
(``[{name, url}]``), its key (optional, sent as ``Authorization: Bearer``) is ``HECATE_KEY_MCP_<NAME>`` in Hecate's
``.env``, written by Hephaestus. Servers still written by hand as ``HECATE_MCP_<NAME>_URL`` / ``_KEY`` keep working
and are moved into the card once, then their old lines are emptied (``connections.ExternalMcpConnector.adopt``).

The list leaves Hecate with names, host and status only: never a URL path, a query or a key.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

SERVERS = "hecate.mcp.servers"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,30}$")
_LEGACY_URL_RE = re.compile(r"^HECATE_MCP_([A-Z0-9_]+)_URL$")

HOW_TO = "Link them in Connections → External MCP servers: name, address and, if it needs one, its key."


def key_name(name: str) -> str:
    """``github`` → the connection key ``mcp_github`` (env ``HECATE_KEY_MCP_GITHUB``)."""
    return f"mcp_{name}"


def valid_url(url: str) -> bool:
    parts = urlsplit(str(url or "").strip())
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def configured(settings: Any) -> list[dict]:
    """The servers of the card: ``[{name, url}]`` (bad rows dropped)."""
    rows = settings.get(SERVERS, []) if settings is not None else []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and NAME_RE.match(str(row.get("name") or "")) and row.get("url"):
            out.append({"name": str(row["name"]), "url": str(row["url"]).strip()})
    return out


def legacy_servers(env: dict[str, str] | None = None) -> list[dict]:
    """Servers written by hand in ``.env`` before the card: ``[{name, url, key}]``."""
    env = dict(os.environ if env is None else env)
    out = []
    for k in sorted(env):
        m = _LEGACY_URL_RE.match(k)
        if m and str(env[k] or "").strip():
            name = m.group(1).lower()
            out.append({"name": name, "url": str(env[k]).strip(),
                        "key": str(env.get(f"HECATE_MCP_{m.group(1)}_KEY") or "").strip()})
    return out


def legacy_envs(name: str) -> list[str]:
    """The old hand-written lines of one server (emptied once it moved into the card)."""
    return [f"HECATE_MCP_{name.upper()}_URL", f"HECATE_MCP_{name.upper()}_KEY"]


def _key_env(name: str) -> str:
    return f"HECATE_KEY_MCP_{name.upper()}"


def bearer_for(name: str, env: dict[str, str] | None = None) -> str | None:
    """The key of one server, for Hecate's own calls (never returned by an endpoint)."""
    env = os.environ if env is None else env
    return ((env.get(_key_env(name)) or "").strip() or (env.get(f"HECATE_MCP_{name.upper()}_KEY") or "").strip()
            or None)


def outbound_servers(settings: Any = None, env: dict[str, str] | None = None) -> list[dict]:
    """Every server, the card's first, then the hand-written ones not moved yet: ``{name, host, auth, status}``."""
    env = dict(os.environ if env is None else env)
    rows = {r["name"]: r["url"] for r in configured(settings)}
    for r in legacy_servers(env):
        rows.setdefault(r["name"], r["url"])
    servers = []
    for name in sorted(rows):
        url = rows[name]
        ok = valid_url(url)
        servers.append({"name": name, "host": urlsplit(url).hostname if ok else None,
                        "auth": "key" if bearer_for(name, env) else "none",
                        "status": "configured" if ok else "invalid_url"})
    return servers


def probe(url: str, key: str = "", *, http: Any = None, timeout: float = 8) -> tuple[bool, str]:
    """«Test»: does an MCP server answer an ``initialize`` at that address (streamable HTTP)? → (ok, reason code)."""
    import requests
    http = http or requests
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "hestia", "version": "1"}}}
    try:
        resp = http.post(url, json=body, headers=headers, timeout=timeout)
    except Exception:  # noqa: BLE001 — the reason in words, never a stack trace
        return False, "unreachable"
    if resp.status_code in (401, 403):
        return False, "key"
    if resp.status_code >= 400:
        return False, f"http_{resp.status_code}"
    return True, "ok"

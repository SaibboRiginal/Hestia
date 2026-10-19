"""Outbound MCP servers: third-party MCP servers Hestia itself may use (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B3).

Hecate owns external providers, so it owns their credentials too. A server is infrastructure + a secret, so it lives
in ``.env`` only, two keys per server::

    HECATE_MCP_<NAME>_URL=https://mcp.example.com/mcp
    HECATE_MCP_<NAME>_KEY=...            # optional: sent as Authorization: Bearer

The list leaves Hecate with names, host and status only: never a URL path, a query or a key.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

_URL_RE = re.compile(r"^HECATE_MCP_([A-Z0-9_]+)_URL$")

HOW_TO = ("Aggiungi nel .env HECATE_MCP_<NOME>_URL (indirizzo del server MCP) e, se serve una chiave, "
          "HECATE_MCP_<NOME>_KEY; poi riavvia Hecate.")


def outbound_servers(env: dict[str, str] | None = None) -> list[dict]:
    env = dict(os.environ if env is None else env)
    servers = []
    for key in sorted(env):
        match = _URL_RE.match(key)
        if not match:
            continue
        name = match.group(1)
        url = str(env[key] or "").strip()
        parts = urlsplit(url)
        valid = parts.scheme in ("http", "https") and bool(parts.hostname)
        has_key = bool(str(env.get(f"HECATE_MCP_{name}_KEY") or "").strip())
        servers.append({"name": name.lower(), "host": parts.hostname if valid else None, "auth": "key" if has_key else "none",
                        "status": "configured" if valid else "invalid_url"})
    return servers


def bearer_for(name: str, env: dict[str, str] | None = None) -> str | None:
    """The key of one server, for Hecate's own calls (never returned by an endpoint)."""
    env = os.environ if env is None else env
    return (env.get(f"HECATE_MCP_{name.upper()}_KEY") or "").strip() or None

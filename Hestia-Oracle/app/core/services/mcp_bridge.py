"""Stdio MCP bridge for the external agent (dossier ``docs/work/2026-10-19-oracle-a-blocchi`` §D).

Started by the agent CLI (Claude Code ``--mcp-config``, Codex ``-c mcp_servers.hestia``) as
``python -m core.services.mcp_bridge`` with ``HESTIA_BRIDGE_URL`` = Oracle's loopback address for this turn
(``…/api/agent-bridge/<token>``). It speaks MCP (JSON-RPC, one message per line) and only forwards ``tools/list`` and
``tools/call`` to Oracle, where the turn's domain-filtered tools run with the usual approval gate. Standard library
only: it runs in the CLI's process tree, outside the web server.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any

PROTOCOL = "2025-06-18"


def _http(method: str, path: str, body: dict | None = None) -> Any:
    url = os.environ["HESTIA_BRIDGE_URL"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as resp:   # a tool waiting for an approval can take long
        return json.loads(resp.read() or b"{}")


def handle(msg: dict, http=_http) -> dict | None:
    """One JSON-RPC message → its response (None for notifications)."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion") or PROTOCOL,
                      "capabilities": {"tools": {}}, "serverInfo": {"name": "hestia", "version": "1.0.0"}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": http("GET", "/tools").get("tools", [])}
        elif method == "tools/call":
            params = msg.get("params") or {}
            out = http("POST", "/call", {"name": params.get("name"), "params": params.get("arguments") or {}})
            result = {"content": [{"type": "text", "text": str(out.get("result", ""))}],
                      "isError": not out.get("ok", False)}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": str(exc)[:300]}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

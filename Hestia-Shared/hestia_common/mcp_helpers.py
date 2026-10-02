"""Shared MCP helper — consistent JSON-RPC tool server for all Hestia services.

Each service imports this module, defines its tools, and mounts the router.
This ensures every service speaks the same MCP protocol without duplicating logic.

Usage:
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router

    tools = [
        MCPTool(name="scout.search", description="Search listings", ...),
        MCPTool(name="scout.reconcile", description="Reconcile data", ...),
    ]
    app.include_router(create_mcp_router(tools, service_name="scout"))
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("hestia_common.mcp")


@dataclass
class MCPTool:
    """Descriptor for one MCP tool with optional Hestia client metadata."""
    name: str
    description: str
    parameters: dict  # JSON Schema for input
    handler: Callable[..., Any]  # async-friendly callable(**params) → result
    # ── Optional Hestia client metadata (Telegram, web UI) ─────────────
    title: str = ""               # Display title for Telegram caption
    method: str = "GET"           # HTTP method for direct execution
    path: str = ""                # Service endpoint path
    clients: list[str] | None = None  # e.g. ["telegram", "ui"] or ["*"]
    response_mode: str = "oracle_natural"  # oracle_natural | direct | raw_json
    response_prompt: str = ""     # Prompt for Oracle LLM formatting
    telegram_visible: bool = True # Show in Telegram /help menu
    telegram_group: str = "altro" # Group in Telegram /help keyboard


def create_mcp_router(tools: list[MCPTool], service_name: str) -> APIRouter:
    """Create a FastAPI router with a standard MCP JSON-RPC /mcp endpoint.

    Supports:
      - tools/list  → returns all tool descriptors
      - tools/call  → executes a named tool with params and returns result
    """
    router = APIRouter()
    tool_map: dict[str, MCPTool] = {t.name: t for t in tools}

    @router.post("/mcp")
    async def mcp_endpoint(request: Request):
        body = await request.json()
        method = body.get("method", "")
        msg_id = body.get("id")

        if method == "tools/list":
            tool_descriptors = []
            for t in tools:
                desc: dict = {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.parameters,
                }
                # Include Hestia client metadata when present
                if t.title:
                    desc["title"] = t.title
                if t.method != "GET":
                    desc["method"] = t.method
                if t.path:
                    desc["path"] = t.path
                if t.clients is not None:
                    desc["clients"] = t.clients
                if t.response_mode != "oracle_natural":
                    desc["response_mode"] = t.response_mode
                if t.response_prompt:
                    desc["response_prompt"] = t.response_prompt
                if not t.telegram_visible:
                    desc["telegram_visible"] = False
                if t.telegram_group != "altro":
                    desc["telegram_group"] = t.telegram_group
                tool_descriptors.append(desc)
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": tool_descriptors},
            })

        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})

            tool = tool_map.get(tool_name)
            if not tool:
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
                })

            try:
                result = tool.handler(**arguments)
                logger.info(
                    "event=mcp_tool_called service=%s tool=%s",
                    service_name, tool_name,
                )
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
                })
            except Exception as exc:
                logger.warning(
                    "event=mcp_tool_error service=%s tool=%s error=%s",
                    service_name, tool_name, exc,
                )
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32000, "message": str(exc)},
                })

        return JSONResponse({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"},
        })

    return router


def mount_missing_rest_routes(app, tools: list[MCPTool], service_name: str = "") -> list[str]:
    """Serve each tool's declared ``method`` + ``path`` when the app lacks it.

    Hub discovery, Telegram and the MCP gateway execute tools by calling the
    declared REST path.  Tools implemented only as MCP handlers used to 404
    there.  This mounts a thin route that calls ``tool.handler``:
    path vars (``{x}`` / ``$x``) + query (GET/DELETE) or JSON body → kwargs.
    Call it AFTER defining the app's own routes.  Returns mounted paths.
    """
    import re

    from fastapi import HTTPException

    existing = set()
    for route in getattr(app, "routes", []):
        for method in getattr(route, "methods", None) or []:
            existing.add((method.upper(), re.sub(r"\{[^}]+\}", "{}", getattr(route, "path", ""))))

    mounted: list[str] = []
    for tool in tools:
        if not tool.path:
            continue
        path = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", r"{\1}", tool.path)
        method = (tool.method or "GET").upper()
        if (method, re.sub(r"\{[^}]+\}", "{}", path)) in existing:
            continue

        def _make(t: MCPTool, m: str):
            async def _endpoint(request: Request):
                params: dict[str, Any] = dict(request.query_params)
                params.update(request.path_params)
                if m in {"POST", "PUT", "PATCH"}:
                    try:
                        body = await request.json()
                    except Exception:
                        body = {}
                    if isinstance(body, dict):
                        params.update(body)
                try:
                    result = t.handler(**params)
                except TypeError as exc:
                    raise HTTPException(status_code=400, detail=f"bad arguments: {exc}")
                except Exception as exc:
                    logger.warning("event=mcp_rest_tool_error service=%s tool=%s error=%s",
                                   service_name, t.name, exc)
                    raise HTTPException(status_code=500, detail=str(exc))
                if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
                    ok, payload = result
                    if not ok:
                        raise HTTPException(status_code=502, detail=str(payload))
                    return payload
                return result
            return _endpoint

        app.add_api_route(path, _make(tool, method), methods=[method], name=f"mcp_rest_{tool.name}")
        existing.add((method, re.sub(r"\{[^}]+\}", "{}", path)))
        mounted.append(f"{method} {path}")
    if mounted:
        logger.info("event=mcp_rest_routes_mounted service=%s routes=%s", service_name, mounted)
    return mounted

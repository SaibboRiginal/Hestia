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

"""Comandi page (WebUI plugin of this module): browse the tools the WebUI sees and run one with arguments.

Same list and same rules as the internal ``/mcp`` for client ``webui`` (the MCPServer is reused, nothing is
duplicated); the page reaches it through the WebUI plugin proxy, so it lives under this plugin's ``api_prefix``
(``/api/mcp/``). SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4.

  GET  /api/mcp/ui/tools         → {commands, count, services}
  POST /api/mcp/ui/tools/call    → {ok, result, error?, response_mode, status_code}
  POST /api/mcp/ui/tools/format  → {ok, text}  (Oracle /api/format, for tools answering in natural language)
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.mcp_server import MCPServer, RpcError

logger = logging.getLogger("hestia_mcp.ui_tools")

CLIENT = "webui"
CALL_TIMEOUT = 20.0     # the WebUI plugin proxy waits 30 s for the whole request
FORMAT_TIMEOUT = 25.0
FORMAT_INSTRUCTIONS = ("Rispondi in italiano conciso. Solo testo semplice: niente HTML, niente Markdown. "
                       "Per gli elenchi usa •.")


def as_command(tool: dict) -> dict:
    """MCP tool → the command shape the page shows (the same one the WebUI used: arguments_schema = JSON schema)."""
    meta = ((tool.get("_meta") or {}).get("hestia") or {})
    name = str(tool.get("name") or "")
    return {
        "command": name,
        "title": str(tool.get("title") or name),
        "description": str(tool.get("description") or ""),
        "service": str(meta.get("service") or ""),
        "method": str(meta.get("method") or "GET"),
        "path": str(meta.get("path") or ""),
        "response_mode": str(meta.get("response_mode") or "oracle_natural"),
        "response_prompt": str(meta.get("response_prompt") or ""),
        "writes": not (tool.get("annotations") or {}).get("readOnlyHint", True),
        "arguments_schema": tool.get("inputSchema") or {"type": "object", "properties": {}},
    }


class CallBody(BaseModel):
    command: str
    args: dict[str, Any] = Field(default_factory=dict)


class FormatBody(BaseModel):
    command: str
    result: Any = None
    response_prompt: str = ""


class UiTools:
    def __init__(self, server: MCPServer, hub_api_url: str):
        self.server = server
        self.hub = hub_api_url.rstrip("/")

    def commands(self) -> list[dict]:
        listed = self.server.tools_list({"_meta": {"hestia": {"client": CLIENT}}}, {"client": CLIENT})
        return [as_command(t) for t in listed.get("tools") or []]

    def call(self, name: str, args: dict) -> dict:
        params = {"name": name, "arguments": args,
                  "_meta": {"hestia": {"client": CLIENT, "timeout_seconds": CALL_TIMEOUT}}}
        try:
            out = self.server.tools_call(params, {"client": CLIENT})
        except RpcError as exc:
            raise HTTPException(status_code=404, detail=exc.message)
        meta = (out.get("_meta") or {}).get("hestia") or {}
        payload = out.get("structuredContent")
        if meta.get("wrapped") and isinstance(payload, dict):
            payload = payload.get("result")
        ok = not out.get("isError")
        cmd = self.server.catalog.find(name) or {}
        res = {"ok": ok, "result": payload, "status_code": meta.get("status_code"),
               "response_mode": str(cmd.get("response_mode") or "oracle_natural")}
        if not ok:
            res["error"] = payload if isinstance(payload, str) else (
                (payload or {}).get("detail") if isinstance(payload, dict) else None) or "Comando non riuscito"
        logger.info("event=ui_tool_run tool=%s ok=%s", name, ok)
        return res

    def format(self, body: FormatBody) -> dict:
        envelope = {"method": "POST", "headers": {}, "query": {}, "timeout_seconds": FORMAT_TIMEOUT,
                    "body": {"command": body.command, "payload": body.result,
                             "response_prompt": body.response_prompt or None,
                             "client_instructions": FORMAT_INSTRUCTIONS, "client": CLIENT}}
        try:
            resp = requests.post(f"{self.hub}/route/oracle/api/format", json=envelope, timeout=FORMAT_TIMEOUT + 3)
            routed = resp.json() if resp.status_code == 200 else {}
            payload = routed.get("payload") if int(routed.get("status_code", 500)) < 400 else None
            text = payload.get("text") if isinstance(payload, dict) else None
        except Exception as exc:  # noqa: BLE001 — the raw result is already on screen
            logger.warning("[🔄] event=ui_tool_format_failed tool=%s error=%s", body.command, exc)
            text = None
        return {"ok": bool(text), "text": text or ""}

    def router(self) -> APIRouter:
        router = APIRouter(prefix="/api/mcp/ui")

        @router.get("/tools")
        def ui_tools():
            commands = self.commands()
            return {"commands": commands, "count": len(commands),
                    "services": sorted({c["service"] for c in commands if c["service"]})}

        @router.post("/tools/call")
        def ui_tools_call(body: CallBody):
            name = body.command.strip()
            if not name:
                raise HTTPException(status_code=400, detail="command required")
            return self.call(name, body.args or {})

        @router.post("/tools/format")
        def ui_tools_format(body: FormatBody):
            return self.format(body)

        return router

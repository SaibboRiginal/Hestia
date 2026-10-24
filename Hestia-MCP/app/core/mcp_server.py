"""Hestia's MCP server: standard MCP over Streamable HTTP (JSON responses) at ``POST /mcp``.

One server for every client (§B2): internal ones (Oracle, Telegram, WebUI) call it through Hub; external AIs
reach it through the WebUI door (P3). Hestia details of each tool travel in ``_meta.hestia``; a caller passes its
context the same way (``params._meta.hestia``: client, session_id, notify_target, trace_id, service,
timeout_seconds, services for tools/list).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from core.catalog import ToolCatalog, to_mcp_tool, visible_to
from core.mcp_settings import SERVER_TIMEOUT, settings

try:
    from hestia_common.tool_call import build_request
except ModuleNotFoundError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "Hestia-Shared"))
    from hestia_common.tool_call import build_request
from hestia_common.display import strip as strip_display

logger = logging.getLogger("hestia_mcp.server")

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "hestia", "title": "Hestia", "version": "1.0.0"}
INSTRUCTIONS = ("Hestia is a personal assistant made of modules. Tools are named <domain>_<verb>. "
                "Reading tools have readOnlyHint=true; changes that need the owner's consent are confirmed by "
                "the owner in Hestia, never here.")


FORBIDDEN = -32003   # an external access may not run this tool (HTTP 403 at the door)


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _hestia(params: dict) -> dict:
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    return meta.get("hestia") if isinstance(meta.get("hestia"), dict) else {}


class MCPServer:
    def __init__(self, catalog: ToolCatalog, hub_api_url: str, version: str = "1.0.0"):
        self.catalog = catalog
        self.hub = hub_api_url.rstrip("/")
        self.info = {**SERVER_INFO, "version": version}

    # ── methods ────────────────────────────────────────────────────────────
    def initialize(self, params: dict, ctx: dict) -> dict:
        asked = str(params.get("protocolVersion") or "")
        version = asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        logger.info("event=mcp_initialize client=%s protocol=%s", ctx.get("client"), version)
        return {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": self.info, "instructions": INSTRUCTIONS}

    def tools_list(self, params: dict, ctx: dict) -> dict:
        services = _hestia(params).get("services")
        tools = self.catalog.tools(ctx.get("client", ""), services if isinstance(services, list) else None)
        if ctx.get("allow") is not None:   # an external access limited to some tools
            tools = [t for t in tools if ctx["allow"](t)]
        if ctx.get("external") and not ctx.get("can_write"):   # read-only access: only reading tools
            tools = [t for t in tools if (t.get("annotations") or {}).get("readOnlyHint")]
        return {"tools": tools}

    def tools_call(self, params: dict, ctx: dict) -> dict:
        name = str(params.get("name") or "")
        args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        hestia = _hestia(params)
        cmd = self.catalog.find(name, str(hestia.get("service") or ""))
        if not cmd or not cmd.get("service") or not cmd.get("path"):
            raise RpcError(-32602, f"Unknown tool: {name}")
        client = ctx.get("client", "")
        tool = to_mcp_tool(cmd)
        if not visible_to(cmd, client) or (ctx.get("allow") is not None and not ctx["allow"](tool)):
            raise RpcError(-32602, f"Unknown tool: {name}")
        writes = not tool["annotations"]["readOnlyHint"]
        if ctx.get("external") and writes and not ctx.get("can_write"):
            raise RpcError(FORBIDDEN, f"This access is read-only: {name} changes something")
        if ctx.get("external"):
            # An external access never chooses session, chat or client: the module sees only who it is.
            call_ctx = {"access": ctx.get("access_name") or "external"}
        else:
            # X-Hestia-Client towards the module = the client the user talks from (given by internal callers),
            # not who calls this server.
            call_ctx = {k: hestia.get(k) for k in ("session_id", "notify_target", "trace_id")}
            if hestia.get("client"):
                call_ctx["client"] = str(hestia["client"])
        req = build_request(cmd, args, call_ctx)
        timeout = float(hestia.get("timeout_seconds") or settings.get(SERVER_TIMEOUT))
        timeout = max(1.0, min(20.0 if ctx.get("external") else 300.0, timeout))   # external: inside the WebUI door
        t0 = time.perf_counter()
        ok, status, payload = self._route(req, timeout)
        logger.info("event=mcp_tool_call tool=%s service=%s client=%s ok=%s status=%s ms=%d", name, req["service"],
                    client or "-", ok, status, int((time.perf_counter() - t0) * 1000))
        if ctx.get("external") and ctx.get("on_call"):
            ctx["on_call"](tool, ok, payload)
        if client != "telegram":
            # The display block is for Telegram's cards (hestia_common.display): models see the plain data.
            payload = strip_display(payload)
        structured = payload if isinstance(payload, dict) else {"result": payload}
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
        return {"content": [{"type": "text", "text": text}], "structuredContent": structured, "isError": not ok,
                "_meta": {"hestia": {"status_code": status, "service": req["service"],
                                     "wrapped": not isinstance(payload, dict)}}}

    def _route(self, req: dict, timeout: float) -> tuple[bool, int, Any]:
        envelope = {"method": req["method"], "headers": req["headers"], "query": req["query"], "body": req["body"],
                    "timeout_seconds": timeout}
        try:
            resp = requests.post(f"{self.hub}/route/{req['service']}/{req['path']}", json=envelope, timeout=timeout + 3)
        except Exception as exc:  # noqa: BLE001
            return False, 0, f"Hub unreachable: {exc}"
        if resp.status_code != 200:
            return False, resp.status_code, f"Hub returned {resp.status_code}: {resp.text[:300]}"
        routed = resp.json() or {}
        status = int(routed.get("status_code", 500))
        return status < 400, status, routed.get("payload")

    # ── JSON-RPC ───────────────────────────────────────────────────────────
    def handle(self, msg: Any, ctx: dict) -> dict | None:
        if not isinstance(msg, dict) or msg.get("jsonrpc", "2.0") != "2.0" or not msg.get("method"):
            return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                    "error": {"code": -32600, "message": "Invalid request"}}
        method, msg_id = str(msg["method"]), msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if msg_id is None:   # notification (e.g. notifications/initialized): nothing to answer
            return None
        handlers = {"initialize": self.initialize, "tools/list": self.tools_list, "tools/call": self.tools_call,
                    "ping": lambda p, c: {}}
        fn = handlers.get(method)
        if not fn:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        try:
            return {"jsonrpc": "2.0", "id": msg_id, "result": fn(params, ctx)}
        except RpcError as exc:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001
            logger.exception("event=mcp_rpc_failed method=%s", method)
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": str(exc)}}

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.post("/mcp")
        async def mcp(request: Request):
            try:
                body = await request.json()
            except ValueError:
                return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                                    status_code=400)
            ctx = {"client": (request.headers.get("x-hestia-client") or "").strip().lower()}
            if isinstance(body, list):
                out = [r for r in (self.handle(m, ctx) for m in body) if r is not None]
                return JSONResponse(out) if out else Response(status_code=202)
            reply = self.handle(body, ctx)
            return JSONResponse(reply) if reply is not None else Response(status_code=202)

        @router.get("/mcp")
        def mcp_stream():
            # No server-initiated messages: the Streamable HTTP spec allows 405 here.
            return Response(status_code=405, headers={"Allow": "POST"})

        return router

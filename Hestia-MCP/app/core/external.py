"""External AIs on Hestia's MCP (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2, §B6).

``POST /mcp/external`` is the same MCP server with an access in front: the WebUI door (``/mcp``, the only
service behind the tunnel) forwards ``Authorization: Bearer <token>`` here through Hub. Wrong, revoked or expired
token → 401; over ``mcp.external.max_calls_per_min`` → 429; a read-only access calling a write tool → 403.
Every call is logged ``event=mcp_external_call``; a write also leaves a silent Hermes inbox entry.
The 401 carries ``WWW-Authenticate: Bearer resource_metadata="…"`` so an OAuth client (claude.ai, ChatGPT) finds the
authorization server (core/oauth.py); OAuth access tokens (``hso_``) pass the same check as ``hst_`` tokens.

``/api/mcp/accesses`` manages accesses (Accessi page, behind the WebUI login). It is not reachable from the door.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from core.access import AccessError, AccessStore, RateLimiter, allows_tool
from core.catalog import EXTERNAL
from core.mcp_server import FORBIDDEN, MCPServer
from core.mcp_settings import EXTERNAL_RATE, settings
from core.oauth import external_tool_list, public_base, www_authenticate

logger = logging.getLogger("hestia_mcp.external")

_HTTP_FOR_ERROR = {FORBIDDEN: 403}


class AccessCreate(BaseModel):
    name: str = Field(..., description="Who uses it, e.g. 'Claude Code PC'")
    scope: str = Field("read", description="read | write")
    tools: list[str] = Field(default_factory=list, description="[] = every tool open to external AIs")
    expires_days: int | None = Field(90, description="0 or null = no expiry")


class AccessPatch(BaseModel):
    name: str | None = None
    scope: str | None = None
    tools: list[str] | None = None
    expires_days: int | None = Field(None, description="0 = no expiry")


def _rpc_error(msg_id: Any, code: int, message: str, status: int, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}},
                        status_code=status, headers=headers)


def setup_lines(token: str, base_url: str = "") -> dict[str, str]:
    """Ready-to-paste lines for the clients that use a token (B3)."""
    url = f"{(base_url or '<indirizzo-di-hestia>').rstrip('/')}/mcp"
    return {
        "url": url,
        "header": f"Authorization: Bearer {token}",
        "claude_code": f'claude mcp add --transport http hestia {url} --header "Authorization: Bearer {token}"',
        "json": json.dumps({"mcpServers": {"hestia": {"type": "http", "url": url,
                                                      "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2),
    }


class ExternalDoor:
    def __init__(self, server: MCPServer, store: AccessStore, hub_api_url: str):
        self.server = server
        self.store = store
        self.hub = hub_api_url.rstrip("/")
        self.limiter = RateLimiter()

    def _inbox(self, access: dict, tool: dict, payload: Any) -> None:
        """Silent Hermes inbox entry for a write by an external AI (no push: Marko reads it when he wants)."""
        title = tool.get("title") or tool.get("name")
        detail = ""
        if isinstance(payload, dict):
            task = payload.get("task") if isinstance(payload.get("task"), dict) else payload
            detail = str(task.get("id") or task.get("proposal_id") or "")[:12]
        text = f"🤖 <b>{access.get('name')}</b> (AI esterna) ha usato <i>{title}</i>" + (f" · {detail}" if detail else "")

        def _run():
            try:
                requests.post(f"{self.hub}/route/hermes/api/dispatch/send",
                              json={"method": "POST", "headers": {}, "query": {}, "timeout_seconds": 8,
                                    "body": {"channel": "", "target": "owner", "message": text,
                                             "metadata": {"source": "mcp", "type": "mcp.external", "quiet": True}}},
                              timeout=10)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[🔄] event=mcp_external_inbox_failed access=%s error=%s", access.get("name"), exc)
        threading.Thread(target=_run, daemon=True, name="mcp-external-inbox").start()

    def _ctx(self, access: dict) -> dict:
        name = str(access.get("name") or "external")

        def on_call(tool: dict, ok: bool, payload: Any) -> None:
            logger.info("event=mcp_external_call access=%s tool=%s ok=%s", name, tool.get("name"), ok)
            self.store.touch(access)
            if ok and not (tool.get("annotations") or {}).get("readOnlyHint"):
                self._inbox(access, tool, payload)

        return {"client": EXTERNAL, "external": True, "access_name": name,
                "can_write": access.get("scope") == "write",
                "allow": lambda tool: allows_tool(access, str(tool.get("name") or "")),
                "on_call": on_call}

    def router(self) -> APIRouter:
        router = APIRouter()
        store = self.store

        @router.post("/mcp/external")
        async def mcp_external(request: Request):
            auth = request.headers.get("authorization") or ""
            token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
            try:
                access, why = store.verify(token)
            except AccessError as exc:
                return _rpc_error(None, -32603, str(exc), 503)
            if access is None:
                logger.info("event=mcp_external_denied reason=%s", why)
                # resource_metadata: where an OAuth client (claude.ai, ChatGPT) starts the authorization (RFC 9728).
                header = www_authenticate(public_base(request), "invalid_token" if token else None)
                return _rpc_error(None, -32001, f"Unauthorized ({why})", 401, {"WWW-Authenticate": header})
            try:
                body = await request.json()
            except ValueError:
                return _rpc_error(None, -32700, "Parse error", 400)
            messages = body if isinstance(body, list) else [body]
            calls = sum(1 for m in messages if isinstance(m, dict) and m.get("id") is not None)
            limit = int(settings.get(EXTERNAL_RATE))
            if calls and not all(self.limiter.allow(access["access_id"], limit) for _ in range(calls)):
                logger.info("event=mcp_external_rate_limited access=%s limit=%d", access.get("name"), limit)
                return _rpc_error(None, -32029, f"Too many calls: max {limit} per minute", 429,
                                  {"Retry-After": "60"})
            ctx = self._ctx(access)
            if isinstance(body, list):
                out = [r for r in (self.server.handle(m, ctx) for m in body) if r is not None]
                return JSONResponse(out) if out else Response(status_code=202)
            reply = self.server.handle(body, ctx)
            if reply is None:
                return Response(status_code=202)
            status = _HTTP_FOR_ERROR.get(((reply.get("error") or {}).get("code")), 200)
            return JSONResponse(reply, status_code=status)

        def _guard(fn, *args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except AccessError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

        @router.get("/api/mcp/accesses")
        def accesses_list():
            return _guard(lambda: {"accesses": store.list()})

        @router.get("/api/mcp/accesses/tools")
        def accesses_tools():
            """Tools a module opened to external AIs (what an access can be limited to)."""
            return {"tools": external_tool_list(self.server.catalog)}

        @router.post("/api/mcp/accesses")
        def accesses_create(body: AccessCreate, base_url: str = ""):
            def _create():
                access, token = store.create(body.name, body.scope, body.tools, body.expires_days)
                return {"access": access, "token": token, "setup": setup_lines(token, base_url)}
            return _guard(_create)

        @router.patch("/api/mcp/accesses/{access_id}")
        def accesses_patch(access_id: str, body: AccessPatch):
            return _guard(lambda: {"access": store.update(access_id, **body.model_dump())})

        @router.post("/api/mcp/accesses/{access_id}/revoke")
        def accesses_revoke(access_id: str):
            return _guard(lambda: {"access": store.revoke(access_id)})

        @router.post("/api/mcp/accesses/{access_id}/renew")
        def accesses_renew(access_id: str, base_url: str = ""):
            def _renew():
                access, token = store.renew(access_id)
                if not token:   # OAuth access: extended, the AI keeps its own (refresh) token
                    return {"access": access, "token": None, "setup": None}
                return {"access": access, "token": token, "setup": setup_lines(token, base_url)}
            return _guard(_renew)

        @router.delete("/api/mcp/accesses/{access_id}")
        def accesses_delete(access_id: str):
            return _guard(lambda: store.delete(access_id))

        @router.get("/api/mcp/outbound")
        def outbound():
            """Servizi esterni: third-party MCP servers Hestia itself would use. Their credentials are Hecate's
            (it owns external providers): names and status only, never a value."""
            try:
                resp = requests.post(f"{self.hub}/route/hecate/api/gateway/outbound/mcp",
                                     json={"method": "GET", "headers": {}, "query": {}, "body": None,
                                           "timeout_seconds": 8}, timeout=11)
                routed = resp.json() if resp.status_code == 200 else {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("[🔄] event=mcp_outbound_list_failed error=%s", exc)
                return JSONResponse({"detail": "Hecate non raggiungibile"}, status_code=503)
            if int(routed.get("status_code", 502)) >= 400:
                return JSONResponse({"detail": "Hecate non raggiungibile"}, status_code=503)
            payload = routed.get("payload") or {}
            return {"servers": payload.get("servers") or [], "how_to": payload.get("how_to")}

        return router

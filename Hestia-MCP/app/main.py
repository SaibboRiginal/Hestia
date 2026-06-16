"""Hestia-MCP — Model Context Protocol Gateway.

Single tool source for the entire Hestia ecosystem.
Aggregates MCP tools from internal services and third-party servers.
Provides domain-filtered tool manifests to Oracle.
Replaces Hub's /discovery/commands as the canonical tool registry.

Endpoints:
  GET  /tools?domains=scout,chronos  → tools for Oracle agent loop
  GET  /tools/all                    → all tools (Telegram command catalog)
  POST /tools/call                   → proxy a tool call
  GET  /health                       → service health
  GET  /api/logs                     → log buffer
"""
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.service_contract import HestiaServiceBase, ServiceDescriptor
from core.tool_registry import ToolRegistry

# ── Logging setup ────────────────────────────────────────────────────────────
try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging

logger, log_buffer = setup_service_logging("hestia_mcp")

# ── Config ───────────────────────────────────────────────────────────────────
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
SERVICE_BASE_URL = os.getenv("MCP_SERVICE_BASE_URL", "http://hestia_mcp:19013")
SERVICE_VERSION = os.getenv("MCP_SERVICE_VERSION", "1.0.0")

# ── Service descriptor ───────────────────────────────────────────────────────

class MCPService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        return {
            "mcp_gateway": True,
            "tool_registry": "/tools",
            "tool_call": "/tools/call",
        }


descriptor = ServiceDescriptor(
    name="mcp",
    base_url=SERVICE_BASE_URL,
    health_endpoint="/health",
    service_type="core",
    service_version=SERVICE_VERSION,
    tags=["core", "mcp", "gateway"],
    topology_tags=["layer:gateway", "domain:mcp", "status:beta"],
)

service = MCPService(descriptor)
registry = ToolRegistry(hub_api_url=HUB_API_URL)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia MCP Gateway", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def on_startup():
    try:
        service.register_to_hub()
        logger.info("event=registered_on_hub hub=%s base_url=%s", HUB_API_URL, SERVICE_BASE_URL)
    except Exception as exc:
        logger.warning("event=hub_registration_failed_non_fatal error=%s", exc)

    # Start keepalive thread
    def _keepalive():
        import time
        while True:
            time.sleep(60)
            try:
                service.register_to_hub()
            except Exception:
                pass
    threading.Thread(target=_keepalive, daemon=True).start()

    # Initial tool cache warm
    try:
        registry.refresh()
    except Exception:
        pass


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_mcp"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {"service": "hestia_mcp", "count": len(rows), "logs": rows}


class ToolCallRequest(BaseModel):
    tool: str
    params: dict = {}
    service: str = ""


@app.get("/tools")
def get_tools(domains: str = Query(default="general", description="Comma-separated domain list")):
    """Return tools for the given domains. Used by Oracle's agent loop."""
    domain_list = [d.strip().lower() for d in domains.split(",") if d.strip()]
    if not domain_list:
        domain_list = ["general"]
    tools = registry.get_tools_for_domains(domain_list)
    return {"domains": domain_list, "count": len(tools), "tools": tools}


@app.get("/tools/all")
def get_all_tools():
    """Return all tools across all domains. Used by Telegram for command catalog."""
    tools = registry.list_all_tools()
    return {"count": len(tools), "tools": tools}


@app.post("/tools/call")
def call_tool(req: ToolCallRequest):
    """Proxy a tool call to the target service via Hub routing."""
    ok, result = registry.call_tool(req.tool, req.params, req.service)
    if not ok:
        raise HTTPException(status_code=502, detail=str(result))
    return {"status": "ok", "tool": req.tool, "result": result}

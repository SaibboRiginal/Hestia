"""Hestia-MCP — Hestia's one MCP server.

Every client lists and calls tools here, the same way (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2):
Oracle, Telegram, the WebUI through Hub; external AIs through the WebUI door.

Endpoints:
  POST /mcp        → MCP (Streamable HTTP, JSON): initialize · tools/list · tools/call · ping
  GET  /health     → service health
  GET  /api/logs   → log buffer
"""
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.service_contract import HestiaServiceBase, ServiceDescriptor
from core.mcp_settings import settings as mcp_settings
from core.catalog import ToolCatalog
from core.mcp_server import MCPServer

# ── Logging setup ────────────────────────────────────────────────────────────
try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging

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
            "mcp_server": "/mcp",
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
catalog = ToolCatalog(hub_api_url=HUB_API_URL)
server = MCPServer(catalog, HUB_API_URL, version=SERVICE_VERSION)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia MCP Gateway", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(mcp_settings.router())
app.include_router(server.router())


@app.on_event("startup")
def on_startup():
    mcp_settings.start()
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
        catalog.commands(refresh=True)
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


app.include_router(create_log_control_router("hestia_mcp"))

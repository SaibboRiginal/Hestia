"""Hestia-MCP — Hestia's one MCP server.

Every client lists and calls tools here, the same way (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2):
Oracle, Telegram, the WebUI through Hub; external AIs through the WebUI door.

Endpoints:
  POST /mcp            → MCP (Streamable HTTP, JSON): initialize · tools/list · tools/call · ping (internal clients)
  POST /mcp/external   → the same MCP for external AIs, behind an access token (WebUI door /mcp forwards here)
  /api/mcp/accesses    → accesses management (Accessi page in the WebUI, plugin of this module)
  /api/mcp/ui/tools    → Comandi page: the tools the WebUI sees, run one (core/ui_tools.py)
  GET  /health         → service health
  GET  /api/logs       → log buffer
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
from core.access import AccessStore
from core.external import ExternalDoor
from core.ui_tools import UiTools

# ── Logging setup ────────────────────────────────────────────────────────────
try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
from hestia_common.plugin_client import PluginClient, page

logger, log_buffer = setup_service_logging("hestia_mcp")

# ── Config ───────────────────────────────────────────────────────────────────
HUB_API_URL = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
SERVICE_BASE_URL = os.getenv("MCP_SERVICE_BASE_URL", "http://hestia_mcp:19013")
SERVICE_VERSION = os.getenv("MCP_SERVICE_VERSION", "1.0.0")
UI_DIST = os.getenv("MCP_UI_DIST", "/ui/dist")   # outside /code: the compose dev mount of app/ must not hide it

# ── WebUI plugin (core module, Sistema section): Comandi & MCP + Accessi AI ──────────────────
ui = PluginClient("mcp", title="Comandi & MCP", icon="command", color="blue", kind="core", dist=UI_DIST,
                  description="Gli strumenti di Hestia e chi li può usare da fuori (AI esterne).",
                  version=SERVICE_VERSION)
ui.webui(entry="mcp.js", api_prefix="/api/mcp/",
         pages=[page("comandi", "Comandi & MCP", element="mcp-commands", icon="terminal", order=190,
                     help="Tutti gli strumenti che Hestia offre (gli stessi di chat, Telegram e AI esterne): "
                          "cerca, leggi i parametri ed eseguili."),
                page("accessi", "Accessi AI", element="mcp-accesses", icon="external", order=191, parent="comandi",
                     help="Token per collegare Claude Code, Claude Desktop, Cursor o un'altra AI agli strumenti di "
                          "Hestia (MCP). Revoca e rinnovo in un tocco.")])

# ── Service descriptor ───────────────────────────────────────────────────────

class MCPService(HestiaServiceBase):
    def build_capabilities(self) -> dict[str, Any]:
        return {
            "mcp_gateway": True,
            "mcp_server": "/mcp",
            "mcp_external": "/mcp/external",
            **ui.capabilities(SERVICE_BASE_URL),
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
accesses = AccessStore(HUB_API_URL)
door = ExternalDoor(server, accesses, HUB_API_URL)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Hestia MCP Gateway", version=SERVICE_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(mcp_settings.router())
app.include_router(server.router())
app.include_router(door.router())
app.include_router(ui.router())
app.include_router(UiTools(server, HUB_API_URL).router())   # Comandi page: /api/mcp/ui/tools…


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

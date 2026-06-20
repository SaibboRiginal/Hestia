import os
from pathlib import Path
import sys
import logging

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

from .core.service_contract import HestiaServiceBase, ServiceDescriptor
from .fetcher import fetch_html
from .schemas import FetchHtmlRequest, FetchHtmlResponse

try:
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, setup_service_logging
    from hestia_common.mcp_helpers import MCPTool, create_mcp_router


class FetchService(HestiaServiceBase):
    def build_capabilities(self) -> dict:
        return {
            "health_check": "/health",
            "mcp_endpoint": f"{SERVICE_BASE_URL.rstrip('/')}/mcp",
            "module_tool_domains": ["web"],
            "fetch_html_endpoint": "/api/fetch/html",
            "commands": [
                {
                    "command": "fetch_page",
                    "title": "Fetch page content",
                    "description": "Fetches HTML by attaching to host Edge via CDP only",
                    "method": "POST",
                    "path": "/api/fetch/html",
                    "clients": ["*"],
                    "response_mode": "raw_json",
                    "telegram_visible": False,
                },
                {
                    "command": "web_search",
                    "title": "Web search",
                    "description": "Search via DuckDuckGo Instant Answer API",
                    "method": "GET",
                    "path": "/api/web/search",
                    "clients": ["*"],
                    "response_mode": "raw_json",
                    "telegram_visible": False,
                    "arguments_schema": {
                        "q": {"type": "string", "description": "Search query", "required": True},
                    },
                },
            ],
        }


load_dotenv()

SERVICE_NAME = os.getenv("SERVICE_NAME", "atlas")
SERVICE_BASE_URL = os.getenv(
    "SERVICE_BASE_URL", "http://host.docker.internal:19014")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "integration")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", "integration").split(",")
    if tag.strip()
]
SERVICE_TOPOLOGY_TAGS = [
    tag.strip().lower()
    for tag in os.getenv(
        "SERVICE_TOPOLOGY_TAGS",
        "layer:gateway,domain:browser,status:stable",
    ).split(",")
    if tag.strip()
]

service = FetchService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
        topology_tags=SERVICE_TOPOLOGY_TAGS,
    )
)

logger, log_buffer = setup_service_logging("hestia_atlas")

app = FastAPI(title="Hestia Atlas", version=SERVICE_VERSION)


@app.on_event("startup")
def register_on_hub_startup():
    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info("event=registered_hub_name_base_url Registered on Hub | name=%s base_url=%s",
                    SERVICE_NAME, SERVICE_BASE_URL)
    except Exception as error:
        logger.warning(
            "event=hub_registration_failed_non_fatal Hub registration failed (non-fatal): %s", error)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "service_type": service.descriptor.service_type,
        "tags": service.descriptor.tags,
    }


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_atlas",
        "count": len(rows),
        "logs": rows,
    }

app.include_router(create_log_control_router("hestia_atlas"))

@app.post("/api/fetch/html", response_model=FetchHtmlResponse)
def fetch_html_endpoint(req: FetchHtmlRequest):
    try:
        result = fetch_html(
            url=req.url,
            timeout_seconds=req.timeout_seconds,
            wait_ms=req.wait_ms,
            strategy=req.strategy,
            cdp_endpoint=req.cdp_endpoint,
        )
        return FetchHtmlResponse(status="ok", **result)
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=FetchHtmlResponse(
                status="error",
                url=req.url,
                error=str(error),
            ).model_dump(),
        )


@app.get("/api/web/search")
def web_search_endpoint(q: str = Query(..., description="Search query")):
    """Search via DuckDuckGo Instant Answer API (Plan 9). Free, no key required."""
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        results: list[dict] = []

        # Abstract (instant answer)
        abstract = str(data.get("Abstract", "") or "").strip()
        if abstract:
            results.append({"type": "abstract", "text": abstract, "url": data.get("AbstractURL", "")})

        # Related topics
        for topic in data.get("RelatedTopics", []) or []:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "type": "related",
                    "text": str(topic.get("Text", "")).strip(),
                    "url": topic.get("FirstURL", ""),
                })

        return {"query": q, "results": results[:10]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": str(exc)})


# ── MCP tools (Plan 9) ────────────────────────────────────────────────────

_atlas_mcp_tools = [
    MCPTool(
        name="fetch_url",
        description="Fetch web page content from a URL via host browser (Edge CDP).",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "timeout_seconds": {"type": "integer", "description": "Fetch timeout (default 15)"},
            },
            "required": ["url"],
        },
        handler=lambda **kw: _fetch_mcp_handler(
            url=str(kw.get("url", "")),
            timeout=int(kw.get("timeout_seconds", 15)),
        ),
        title="🌐 Fetch URL", method="POST", path="/api/fetch/html",
        clients=["*"], response_mode="raw_json",
        telegram_visible=False, telegram_group="web",
    ),
    MCPTool(
        name="web_search",
        description="Search the web via DuckDuckGo Instant Answer API (free, no key).",
        parameters={
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
            },
            "required": ["q"],
        },
        handler=lambda **kw: _web_search_mcp_handler(q=str(kw.get("q", ""))),
        title="🔍 Web Search", method="GET", path="/api/web/search",
        clients=["*"], response_mode="raw_json",
        telegram_visible=False, telegram_group="web",
    ),
]


def _fetch_mcp_handler(url: str, timeout: int = 15) -> tuple[bool, dict]:
    try:
        result = fetch_html(url=url, timeout_seconds=timeout)
        return (True, result)
    except Exception as exc:
        return (False, {"error": str(exc)})


def _web_search_mcp_handler(q: str) -> tuple[bool, dict]:
    try:
        resp = requests.get(
            "https://api.duckduckgo.com/",
            params={"q": q, "format": "json", "no_html": "1", "skip_disambig": "1"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        results: list[dict] = []
        abstract = str(data.get("Abstract", "") or "").strip()
        if abstract:
            results.append({"type": "abstract", "text": abstract, "url": data.get("AbstractURL", "")})
        for topic in data.get("RelatedTopics", []) or []:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({"type": "related", "text": str(topic["Text"]).strip(), "url": topic.get("FirstURL", "")})
        return (True, {"query": q, "results": results[:10]})
    except Exception as exc:
        return (False, {"error": str(exc)})


try:
    app.include_router(create_mcp_router(_atlas_mcp_tools, service_name="atlas"))
    logger.info("event=mcp_router_mounted service=atlas tools=%d", len(_atlas_mcp_tools))
except Exception as exc:
    logger.warning("event=mcp_router_mount_failed service=atlas error=%s", exc)


if __name__ == "__main__":
    host = os.getenv("FETCH_HOST", "0.0.0.0")
    port = int(os.getenv("FETCH_PORT", "8095"))
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
    )

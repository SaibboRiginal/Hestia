import os
from pathlib import Path
import sys
import logging

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from .core.service_contract import HestiaServiceBase, ServiceDescriptor
from .fetcher import fetch_html
from .schemas import FetchHtmlRequest, FetchHtmlResponse

try:
    from hestia_common.logging_utils import setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import setup_service_logging


class FetchService(HestiaServiceBase):
    def build_capabilities(self) -> dict:
        return {
            "health_check": "/health",
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
                }
            ],
        }


load_dotenv()

SERVICE_NAME = os.getenv("SERVICE_NAME", "atlas")
SERVICE_BASE_URL = os.getenv(
    "SERVICE_BASE_URL", "http://host.docker.internal:19009")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
SERVICE_TYPE = os.getenv("SERVICE_TYPE", "integration")
SERVICE_TAGS = [
    tag.strip().lower()
    for tag in os.getenv("SERVICE_TAGS", "integration").split(",")
    if tag.strip()
]

service = FetchService(
    ServiceDescriptor(
        name=SERVICE_NAME,
        base_url=SERVICE_BASE_URL,
        service_type=SERVICE_TYPE,
        service_version=SERVICE_VERSION,
        tags=SERVICE_TAGS,
    )
)

logger, log_buffer = setup_service_logging("hestia_atlas")

app = FastAPI(title="Hestia Atlas", version=SERVICE_VERSION)


@app.on_event("startup")
def register_on_hub_startup():
    try:
        service.register_to_hub(timeout_seconds=4)
        logger.info("Registered on Hub | name=%s base_url=%s",
                    SERVICE_NAME, SERVICE_BASE_URL)
    except Exception as error:
        logger.warning("Hub registration failed (non-fatal): %s", error)


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


if __name__ == "__main__":
    host = os.getenv("FETCH_HOST", "0.0.0.0")
    port = int(os.getenv("FETCH_PORT", "8095"))
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")

import logging
import os
from pathlib import Path
import sys
import threading
import time
import requests

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from hestia_common.logging_utils import log_event, setup_service_logging
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import log_event, setup_service_logging

from .modules.schemas import DispatchSendRequest, EventIngestRequest, OutboundEventStateUpdateRequest
from .modules.service import HermesService

logger, log_buffer = setup_service_logging("hestia_hermes")

app = FastAPI(title="Hestia Hermes", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
service = HermesService()


@app.on_event("startup")
def register_on_hub_startup():
    hub_api_url = os.getenv(
        "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
    service_base_url = os.getenv(
        "HERMES_SERVICE_BASE_URL", "http://hestia_hermes:19005")
    payload = {
        "name": "hermes",
        "base_url": service_base_url,
        "health_endpoint": "/health",
        "service_type": "core",
        "service_version": os.getenv("HERMES_SERVICE_VERSION", "1.0.0"),
        "tags": ["core", "dispatch"],
        "capabilities": {
            "event_ingest": "/api/events/ingest"
        },
    }
    max_attempts = int(os.getenv("HERMES_HUB_REGISTER_RETRIES", "8"))
    retry_delay = float(os.getenv("HERMES_HUB_REGISTER_RETRY_DELAY", "2"))

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(
                f"{hub_api_url}/registry/register", json=payload, timeout=4)
            if response.status_code < 400:
                log_event(
                    logger,
                    logging.INFO,
                    "hub_register_success",
                    service="hermes",
                    attempt=attempt,
                    hub=hub_api_url,
                    base_url=service_base_url,
                    status_code=response.status_code,
                )
                return

            log_event(
                logger,
                logging.WARNING,
                "hub_register_non_success",
                service="hermes",
                attempt=attempt,
                hub=hub_api_url,
                status_code=response.status_code,
                body_preview=response.text[:250],
            )
        except Exception as error:
            log_event(
                logger,
                logging.WARNING,
                "hub_register_exception",
                service="hermes",
                attempt=attempt,
                hub=hub_api_url,
                error=str(error),
            )

        if attempt < max_attempts:
            time.sleep(max(0.0, retry_delay))

    log_event(
        logger,
        logging.ERROR,
        "hub_register_exhausted",
        service="hermes",
        attempts=max_attempts,
        hub=hub_api_url,
    )

    # Regardless of initial result, keep re-registering so a Hub restart doesn't lose this service.
    def _hub_keepalive():
        while True:
            time.sleep(60)
            try:
                requests.post(f"{hub_api_url}/registry/register",
                              json=payload, timeout=4)
            except Exception as error:
                log_event(
                    logger,
                    logging.WARNING,
                    "hub_keepalive_exception",
                    service="hermes",
                    hub=hub_api_url,
                    error=str(error),
                )
    threading.Thread(target=_hub_keepalive, daemon=True,
                     name="hub-keepalive").start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hermes"}


@app.get("/api/logs")
def get_logs(limit: int = 200, level: str | None = None, contains: str | None = None):
    rows = log_buffer.query(limit=limit, level=level, contains=contains)
    return {
        "service": "hestia_hermes",
        "count": len(rows),
        "logs": rows,
    }


@app.post("/api/events/ingest")
def ingest_event(req: EventIngestRequest):
    log_event(
        logger,
        logging.INFO,
        "event_received",
        service="hermes",
        event_type=req.event_type,
        domain=req.domain,
        entity_id=req.entity_id,
        payload_keys=sorted(list(req.payload.keys())) if isinstance(
            req.payload, dict) else [],
    )
    result = service.process_event(
        event_type=req.event_type,
        domain=req.domain,
        entity_id=req.entity_id,
        payload=req.payload,
    )
    log_event(
        logger,
        logging.INFO,
        "event_processed",
        service="hermes",
        event_type=req.event_type,
        domain=req.domain,
        entity_id=req.entity_id,
        subscriptions_matched=result["subscriptions_matched"],
        deliveries=result["deliveries"],
    )
    return {"status": "ok", "result": result}


@app.post("/api/dispatch/send")
def send_dispatch(req: DispatchSendRequest):
    ok, detail = service.dispatch.send(
        channel=req.channel,
        target=req.target,
        message=req.message,
        metadata=req.metadata,
    )
    return {"success": ok, "detail": detail}


@app.post("/api/outbound-events/state")
def update_outbound_event_state(req: OutboundEventStateUpdateRequest):
    updated = service.update_outbound_event_state(
        outbound_event_id=req.outbound_event_id,
        lifecycle_state=req.lifecycle_state,
        detail=req.detail,
        superseded_by=req.superseded_by,
    )
    return {"status": "ok", "updated": bool(updated)}

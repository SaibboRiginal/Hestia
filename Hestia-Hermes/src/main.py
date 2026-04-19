import logging
import os
import time
import requests

from fastapi import FastAPI

from .modules.schemas import DispatchSendRequest, EventIngestRequest
from .modules.service import HermesService

logging.basicConfig(
    # LOG_LEVEL: DEBUG | INFO | WARNING | ERROR
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("hestia_hermes")

app = FastAPI(title="Hestia Hermes", version="1.0.0")
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
                logger.info(
                    "Registered on Hub | attempt=%s hub=%s base_url=%s",
                    attempt,
                    hub_api_url,
                    service_base_url,
                )
                return

            logger.warning(
                "Hub registration returned non-success | attempt=%s status=%s body=%s",
                attempt,
                response.status_code,
                response.text[:250],
            )
        except Exception as error:
            logger.warning(
                "Hub registration failed | attempt=%s error=%s",
                attempt,
                error,
            )

        if attempt < max_attempts:
            time.sleep(max(0.0, retry_delay))

    logger.error(
        "Unable to register Hermes on Hub after %s attempt(s)",
        max_attempts,
    )


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hermes"}


@app.post("/api/events/ingest")
def ingest_event(req: EventIngestRequest):
    logger.info(
        "Event received | type=%s domain=%s entity_id=%s payload_keys=%s",
        req.event_type,
        req.domain,
        req.entity_id,
        sorted(list(req.payload.keys())) if isinstance(
            req.payload, dict) else [],
    )
    result = service.process_event(
        event_type=req.event_type,
        domain=req.domain,
        entity_id=req.entity_id,
        payload=req.payload,
    )
    logger.info(
        "Event processed | type=%s domain=%s entity_id=%s matched=%s deliveries=%s",
        req.event_type,
        req.domain,
        req.entity_id,
        result["subscriptions_matched"],
        result["deliveries"],
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

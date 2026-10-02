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
    from hestia_common.logging_utils import create_log_control_router, log_event, setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready, wait_for_hub_services
except ModuleNotFoundError:
    _workspace_root = Path(__file__).resolve().parents[2]
    _shared_pkg = _workspace_root / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.logging_utils import create_log_control_router, log_event, setup_service_logging
    from hestia_common.startup_utils import hub_health_url, wait_for_http_ready, wait_for_hub_services

from .modules.schemas import DispatchSendRequest, EventIngestRequest, OutboundEventStateUpdateRequest
from .modules.service import HermesService

logger, log_buffer = setup_service_logging("hestia_hermes")

app = FastAPI(title="Hestia Hermes", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
service = HermesService()


def _bootstrap_system_subscription(hub_api_url: str) -> None:
    """Ensure a permanent subscription exists for service.action_required events.
    Idempotent — if it already exists, Archive handles the duplicate gracefully."""
    notify_target = os.getenv("NOTIFY_TARGET", "").strip()
    if not notify_target:
        logger.warning("event=system_subscription_skipped reason=NOTIFY_TARGET_not_set")
        return
    try:
        resp = requests.post(
            f"{hub_api_url}/route/archive/api/subscriptions",
            json={
                "method": "POST",
                "headers": {},
                "query": {},
                "body": {
                    "subscription_id": f"sys-action-required-{notify_target}",
                    "domain": "system",
                    "event_type": "service.action_required",
                    "filters": {},
                    "channels": [{"type": "telegram", "target": notify_target}],
                    "owner": str(notify_target),
                    "is_active": True,
                },
                "timeout_seconds": 8,
            },
            timeout=10,
        )
        if resp.status_code < 400:
            logger.info("event=system_subscription_bootstrapped")
        else:
            logger.warning(
                "event=system_subscription_bootstrap_failed "
                "status=%s body=%s",
                resp.status_code,
                resp.text[:300],
            )
    except Exception as exc:
        logger.warning("event=system_subscription_bootstrap_failed error=%s", exc)


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
        "topology_tags": ["layer:foundation", "domain:dispatch", "status:stable"],
        "capabilities": {
            "event_ingest": "/api/events/ingest"
        },
    }
    max_attempts = int(os.getenv("HERMES_HUB_REGISTER_RETRIES", "8"))
    retry_delay = float(os.getenv("HERMES_HUB_REGISTER_RETRY_DELAY", "2"))
    startup_wait_timeout = float(
        os.getenv("STARTUP_WAIT_TIMEOUT_SECONDS", "0"))

    wait_for_http_ready(
        hub_health_url(hub_api_url),
        timeout_seconds=startup_wait_timeout,
        logger=logger,
        description="hub",
    )

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
                # Wait for Archive before bootstrapping subscriptions.
                # Without Archive, event processing silently returns 0 matches.
                wait_for_hub_services(
                    hub_api_url,
                    ["archive"],
                    timeout_seconds=30,
                    interval_seconds=1.5,
                    logger=logger,
                )
                _bootstrap_system_subscription(hub_api_url)
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


@app.on_event("startup")
def start_delivery_retry_loop():
    """Background pass retrying failed deliveries (resilience rule 7)."""
    interval = float(os.getenv("HERMES_RETRY_INTERVAL_SECONDS", "120"))

    def _loop():
        while True:
            time.sleep(max(15.0, interval))
            try:
                service.retry_failed_deliveries()
            except Exception as exc:
                logger.warning("[🔄] event=hermes_retry_loop_error error=%s", exc)

    threading.Thread(target=_loop, daemon=True, name="hermes-retry").start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hermes"}

app.include_router(create_log_control_router("hestia_hermes"))

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
    trace_id = ""
    if isinstance(req.payload, dict):
        trace_id = str(req.payload.get("trace_id")
                       or req.payload.get("x_trace_id") or "").strip()
    log_event(
        logger,
        logging.INFO,
        "event_received",
        service="hermes",
        event_type=req.event_type,
        domain=req.domain,
        entity_id=req.entity_id,
        trace_id=trace_id,
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
        trace_id=trace_id,
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

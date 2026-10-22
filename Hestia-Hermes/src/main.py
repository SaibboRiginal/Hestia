import logging
import os
from pathlib import Path
import sys
import threading
import time
import requests

from fastapi import FastAPI, HTTPException
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

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .modules.schemas import (
    DispatchSendRequest,
    EventIngestRequest,
    NotificationAnswerRequest,
    NotificationClientRequest,
    NotificationOutcomeRequest,
    NotificationSeenAllRequest,
    OutboundEventStateUpdateRequest,
)
from .modules.hermes_settings import DELIVERY_RETRY_INTERVAL, settings as hermes_settings
from .modules.service import HermesService
from .modules import ui_view
from hestia_common.plugin_client import PluginClient, page, widget
from hestia_common import recap

logger, log_buffer = setup_service_logging("hestia_hermes")

SERVICE_VERSION = os.getenv("HERMES_SERVICE_VERSION", "1.0.0")
UI_DIST = os.getenv("HERMES_UI_DIST", "/ui/dist")   # outside /code: the compose dev mount of src/ must not hide it

app = FastAPI(title="Hestia Hermes", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[
                   "*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(hermes_settings.router())
service = HermesService()

# ── WebUI plugin (core module, Sistema section): Notifiche (inbox) + Consegne ────────────────────
# Routes of Hermes are spread over /api/notifications, /api/events…: the plugin reads /api/ui/* only.
ui = PluginClient("hermes", title="Hermes", icon="bell", color="teal", kind="core", dist=UI_DIST,
                  description="Cosa Hermes ha consegnato a quale client: trattenute, silenziose, ritirate, risposte.",
                  version=SERVICE_VERSION)
ui.webui(entry="hermes.js", api_prefix="/api/ui/",
         pages=[page("notifiche", "Notifiche", element="hermes-inbox", icon="bell", order=140,
                     badge={"source": "/api/ui/inbox/counts", "field": "unread"},
                     help="L'elenco delle notifiche, uguale su ogni client (letta qui = letta su Telegram): "
                          "da leggere, da rispondere, tutte; i pulsanti rispondono al modulo che ha chiesto."),
                page("consegne", "Consegne", element="hermes-deliveries", icon="send", order=141, parent="notifiche",
                     help="Ogni notifica e a quali client è arrivata (Telegram, WebUI…): trattenuta dalla presenza, "
                          "silenziosa, ritirata dalla chat, risposta. L'elenco da leggere è in Notifiche.")],
         widgets=[widget("oggi", "Consegne oggi", element="hermes-today-widget", sizes=["s", "m"], auto=True,
                         open_page="consegne", icon="bell",
                         help="Notifiche di oggi: consegnate, trattenute, fallite, in attesa di risposta.")])
app.include_router(ui.router())


def _bootstrap_system_subscription(hub_api_url: str) -> None:
    """Ensure a permanent subscription exists for service.action_required events.
    Idempotent — if it already exists, Archive handles the duplicate gracefully."""
    # Notices go to the user ("owner") on every client (SPEC hermes-global-notifications).
    notify_target = "owner"
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
                    "channels": [{"type": "all", "target": notify_target}],
                    "owner": str(notify_target),
                    "is_active": True,
                },
                "timeout_seconds": 8,
            },
            timeout=10,
        )
        if resp.status_code < 400:
            logger.info("event=system_subscription_bootstrapped")
            _deactivate_legacy_system_subscriptions(
                hub_api_url, f"sys-action-required-{notify_target}")
        else:
            logger.warning(
                "event=system_subscription_bootstrap_failed "
                "status=%s body=%s",
                resp.status_code,
                resp.text[:300],
            )
    except Exception as exc:
        logger.warning("event=system_subscription_bootstrap_failed error=%s", exc)


def _deactivate_legacy_system_subscriptions(hub_api_url: str, keep_id: str) -> None:
    """Older installs keyed the system subscription by a hardcoded chat id
    (sys-action-required-<id>). Turn those off so alerts are not sent twice."""
    def _route(method: str, path: str, query: dict | None = None, body: dict | None = None):
        return requests.post(
            f"{hub_api_url}/route/archive/{path}",
            json={"method": method, "headers": {}, "query": query or {},
                  "body": body or {}, "timeout_seconds": 8},
            timeout=10,
        )
    try:
        resp = _route("GET", "api/subscriptions/active",
                      query={"domain": "system", "event_type": "service.action_required"})
        envelope = resp.json() if resp.status_code < 400 else {}
        rows = envelope.get("payload") if isinstance(envelope, dict) else None
        for row in rows if isinstance(rows, list) else []:
            sub_id = str((row or {}).get("subscription_id") or "")
            if sub_id.startswith("sys-action-required-") and sub_id != keep_id:
                _route("PATCH", f"api/subscriptions/{sub_id}/active", body={"is_active": False})
                logger.info("event=legacy_system_subscription_deactivated subscription_id=%s", sub_id)
    except Exception as exc:
        logger.warning("[🔄] event=legacy_system_subscription_cleanup_failed error=%s", exc)


def _register_agenda() -> None:
    """Periodic work is an agenda job (Chronos), not a Hermes loop."""
    try:
        from hestia_common.agenda_client import AgendaClient, job_rule
    except ModuleNotFoundError:
        return
    AgendaClient("hermes").register_async([job_rule(
        "hermes.notifications.retract",
        "Pulizia notifiche già gestite dai client",
        service="hermes", path="/api/notifications/retract-stale",
        recurrence="FREQ=HOURLY",
        description="Toglie dalla chat Telegram le notifiche già viste o gestite (restano nell'elenco della WebUI).",
        timeout_seconds=60,
    )])


@app.on_event("startup")
def start_settings():
    hermes_settings.start()


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
        "service_version": SERVICE_VERSION,
        "tags": ["core", "dispatch"],
        "topology_tags": ["layer:foundation", "domain:dispatch", "status:stable"],
        "capabilities": {
            "event_ingest": "/api/events/ingest",
            "notifications": "/api/notifications",
            **recap.capabilities(),
            **ui.capabilities(service_base_url),
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

    # Regardless of the initial result, keep re-registering so a Hub restart doesn't lose this service.
    # Started first: the success path returns early (it used to skip this, so the Hub saw Hermes offline
    # after 3 minutes and lost it on restart — found by the cloud test bench, 2026-10-19).
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
                _register_agenda()
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



@app.on_event("startup")
def start_delivery_retry_loop():
    """Background pass retrying failed deliveries (resilience rule 7)."""
    def _loop():
        while True:
            # Read at every pass: a change of hermes.delivery.retry_interval applies live.
            time.sleep(max(15.0, float(hermes_settings.get(DELIVERY_RETRY_INTERVAL))))
            try:
                service.retry_failed_deliveries()
            except Exception as exc:
                logger.warning("[🔄] event=hermes_retry_loop_error error=%s", exc)

    threading.Thread(target=_loop, daemon=True, name="hermes-retry").start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "hestia_hermes"}

app.include_router(create_log_control_router("hestia_hermes"))

# Daily recap piece (docs/work/2026-10-20-recap-giornaliero): notifications of the day, answers still awaited.
app.include_router(recap.recap_router(
    "hermes", lambda day, nxt: recap.piece("hermes", "Notifiche", icon="bell", emoji="🔔", order=800,
                                         **service.notifications.recap(day.isoformat()))))

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
    ok, detail = service.send_direct(
        channel=req.channel,
        target=req.target,
        message=req.message,
        metadata=req.metadata,
        actions=req.actions,
    )
    return {"success": ok, "detail": detail}


# ── Notifications (global, every client) ─────────────────────────────────────

@app.get("/api/notifications")
def list_notifications(filter: str = "all", source: str = "", before: str = "",
                       limit: int = 50, client: str = ""):
    """Inbox: ``filter`` all | unread | pending (waiting for an answer)."""
    return service.notifications.inbox(filter_=filter, source=source, before=before,
                                       limit=limit, client=client)


@app.get("/api/notifications/counts")
def notification_counts(client: str = ""):
    return service.notifications.counts(client)


@app.get("/api/notifications/clients")
def notification_clients():
    return {"clients": [c.name for c in service.notifications.clients.clients(force=True)]}


@app.post("/api/notifications/seen-all")
def notifications_seen_all(req: NotificationSeenAllRequest):
    return service.notifications.mark_all_seen(req.client, req.delivered_to)


class ReleaseHeldRequest(BaseModel):
    level: str = ""


@app.post("/api/notifications/release-held")
def notifications_release_held(req: ReleaseHeldRequest | None = None):
    """Chronos presence: the notification level opened again → one digest of what was held."""
    return service.notifications.release_held((req or ReleaseHeldRequest()).level)


@app.post("/api/notifications/retract-stale")
def notifications_retract_stale():
    """Agenda job: drop handled messages from transient client surfaces (Telegram chat)."""
    return service.notifications.retract_stale()


@app.post("/api/notifications/{notification_id}/seen")
def notification_seen(notification_id: str, req: NotificationClientRequest):
    return service.notifications.mark_seen(notification_id, req.client)


@app.post("/api/notifications/{notification_id}/answer")
def notification_answer(notification_id: str, req: NotificationAnswerRequest):
    """First answer wins (409 already_handled for the others); the action is
    routed to the module that asked."""
    status, body = service.notifications.answer(notification_id, req.action_id, req.client)
    return JSONResponse(status_code=status, content=body)


@app.post("/api/notifications/{notification_id}/answer/outcome")
def notification_answer_outcome(notification_id: str, req: NotificationOutcomeRequest):
    """Outcome of a legacy command action executed by the answering client."""
    return service.notifications.report_outcome(notification_id, req.client, req.ok, req.text)


@app.post("/api/outbound-events/state")
def update_outbound_event_state(req: OutboundEventStateUpdateRequest):
    updated = service.update_outbound_event_state(
        outbound_event_id=req.outbound_event_id,
        lifecycle_state=req.lifecycle_state,
        detail=req.detail,
        superseded_by=req.superseded_by,
    )
    return {"status": "ok", "updated": bool(updated)}


# ── Inside view (WebUI plugin «Consegne»): read-only ─────────────────────────

def _ui_guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ui_view.ArchiveUnavailable:
        logger.warning("[🔄] event=hermes_ui_archive_unavailable")
        raise HTTPException(status_code=502, detail="archivio non disponibile")


@app.get("/api/ui/deliveries")
def ui_deliveries(since: str = "", before: str = "", limit: int = 50, flag: str = "", client: str = "",
                  source: str = ""):
    """Delivery log: per notification, the state on every client + held/quiet/retracted/answer.
    ``flag`` held | quiet | retracted | failed | answered | superseded | pending; ``before`` = page cursor."""
    return _ui_guard(ui_view.deliveries, service.archive, since=since, before=before, limit=limit,
                     flag=flag, client=client, source=source)


@app.get("/api/ui/subscriptions")
def ui_subscriptions():
    """Active subscriptions (what makes an event become a notification)."""
    return _ui_guard(ui_view.subscriptions, service.archive)


@app.get("/api/ui/clients")
def ui_clients():
    """Clients Hermes delivers to right now (Hub topology ``layer:client`` + notify_endpoint)."""
    return notification_clients()


# ── Inbox (WebUI plugin «Notifiche»): thin /api/ui/ doors on the routes above ──
# The WebUI proxy only lets a plugin call its api_prefix (/api/ui/), so the inbox page reaches the same logic
# here. The plugin is a WebUI surface: the client is "webui" unless told otherwise (read on WebUI = read everywhere).

UI_CLIENT = "webui"


class UiClientRequest(BaseModel):
    client: str = UI_CLIENT


class UiAnswerRequest(BaseModel):
    action_id: str
    client: str = UI_CLIENT


@app.get("/api/ui/inbox")
def ui_inbox(filter: str = "all", source: str = "", before: str = "", limit: int = 40, client: str = UI_CLIENT):
    """Inbox page: same as ``GET /api/notifications`` for the WebUI client."""
    return list_notifications(filter=filter, source=source, before=before, limit=limit, client=client or UI_CLIENT)


@app.get("/api/ui/inbox/counts")
def ui_inbox_counts(client: str = UI_CLIENT):
    """``{unread, pending}`` — also the sidebar badge source of the Notifiche page."""
    return notification_counts(client or UI_CLIENT)


@app.post("/api/ui/inbox/seen-all")
def ui_inbox_seen_all(req: UiClientRequest | None = None):
    return notifications_seen_all(NotificationSeenAllRequest(client=(req or UiClientRequest()).client or UI_CLIENT))


@app.post("/api/ui/inbox/{notification_id}/seen")
def ui_inbox_seen(notification_id: str, req: UiClientRequest | None = None):
    return notification_seen(notification_id, NotificationClientRequest(client=(req or UiClientRequest()).client or UI_CLIENT))


@app.post("/api/ui/inbox/{notification_id}/answer")
def ui_inbox_answer(notification_id: str, req: UiAnswerRequest):
    """First answer wins (409 ``already_handled`` with the winning ``answer``)."""
    return notification_answer(notification_id, NotificationAnswerRequest(action_id=req.action_id,
                                                                          client=req.client or UI_CLIENT))

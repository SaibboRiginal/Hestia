"""Monitor service — background polling loop.

Each cycle (every ``argus.poll.interval`` seconds, central setting):
  1. Queries Hub for the current service registry.
  2. Polls each service's /health endpoint.
  3. Fetches only NEW log lines from each container (incremental cursor).
  4. Dispatches deduplicated alerts via Hermes for:
       - Health issues (down / degraded)
       - Log events at WARNING / ERROR / CRITICAL level
  5. Sends recovery notifications when a previously-alerted service comes back.
  6. Checks Hecate provider auth status and emits service.action_required
     events for any broken provider (Google / Outlook).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from core import argus_settings as cfg
from core import docker_client, forge_proposer, health_poller, hub_client

try:
    from hestia_common.agenda_client import AgendaClient, template as agenda_template
except ModuleNotFoundError:  # local run without the shared package on sys.path
    AgendaClient = None  # type: ignore[assignment]
    agenda_template = None  # type: ignore[assignment]
from schemas.reports import LogEvent
from schemas.reports import ServiceAlert
from worker.alert_worker import send_alert, send_recovery

logger = logging.getLogger(f"hestia_argus.{__name__}")

# Services currently known to be unhealthy — used to detect recovery.
# Value is the last known bad status string.
_unhealthy: dict[str, str] = {}
_unhealthy_lock = threading.Lock()
_seen_log_fingerprints: set[str] = set()
_seen_log_order: deque[str] = deque()
_seen_log_lock = threading.Lock()
_monitor_cycle_count: int = 0

# ── Repair follow-up in the assistant agenda ────────────────────────────────
# A service that stays down is not forgotten: Argus plans "argus.repair.<svc>"
# rechecks in Hestia's agenda (fired by Chronos → POST /api/argus/recheck/<svc>)
# with exponential backoff; each recheck re-requests the Hephaestus repair.
# The user sees them and can move/cancel. Recovery closes the entry.
_repair_attempts: dict[str, int] = {}
_agenda = AgendaClient("argus", hub_client.HUB_API_URL) if AgendaClient else None


def _repair_key(service: str) -> str:
    return f"argus.repair.{service}"


def _plan_recheck(service: str, status: str, error: str | None) -> None:
    if _agenda is None:
        return
    attempt = _repair_attempts.get(service, 0) + 1
    _repair_attempts[service] = attempt
    first = cfg.get_int(cfg.REPAIR_RECHECK, 1)
    cap = max(first, cfg.get_int(cfg.REPAIR_RECHECK_MAX, 1))
    minutes = min(cap, first * 2 ** (attempt - 1))
    when = datetime.now(timezone.utc).timestamp() + minutes * 60
    _agenda.plan(
        _repair_key(service), f"🩺 Ricontrollo {service} ({status}) — tentativo {attempt}",
        datetime.fromtimestamp(when, tz=timezone.utc),
        action={"service": "argus", "path": f"/api/argus/recheck/{service}", "method": "POST",
                "body": {"trigger": "agenda"}, "timeout_seconds": 30},
        description=f"Servizio {service} non sano: {str(error or 'unknown')[:200]}. "
                    "Argus ricontrolla e richiede di nuovo la riparazione a Hephaestus.",
        params={"service": service, "attempt": attempt})


def _close_repair(service: str) -> None:
    if _repair_attempts.pop(service, None) is not None and _agenda is not None:
        _agenda.done(_repair_key(service))


def recheck(service: str) -> dict:
    """Agenda follow-up for an unhealthy service: still down → repair again + next recheck."""
    target = next((s for s in hub_client.discover_services() if s.get("name") == service), None)
    if target is None:
        report_status, error = "down", "not registered on Hub"
    else:
        report = health_poller.poll_service(target)
        report_status, error = report.status, report.error
    if report_status == "up":
        _close_repair(service)
        with _unhealthy_lock:
            was = _unhealthy.pop(service, None)
        if was:
            send_recovery(service)
        return {"status": "ok", "service": service, "health": "up"}
    ok, response = (False, {"skipped": "auto_remediate_disabled"})
    if cfg.get_bool(cfg.REMEDIATE_ENABLED):
        ok, response = hub_client.request_hephaestus_remediation(
            source="argus.recheck", service=service, issue=f"service_{report_status}",
            severity="critical" if report_status == "down" else "warning",
            requested_action="auto_health_recovery", environment=cfg.get_str(cfg.REMEDIATE_ENVIRONMENT),
            dry_run=cfg.get_bool(cfg.REMEDIATE_DRY_RUN), auto_approve=False,
            metadata={"status": report_status, "error": error, "recheck_attempt": _repair_attempts.get(service, 0)})
    _plan_recheck(service, report_status, error)
    logger.info("[🔄] event=argus_recheck_still_unhealthy service=%s status=%s remediation_ok=%s next_attempt=%d",
                service, report_status, ok, _repair_attempts.get(service, 0))
    return {"status": "ok", "service": service, "health": report_status,
            "remediation_requested": ok, "remediation": response,
            "next_attempt": _repair_attempts.get(service, 0)}


def _is_new_log_event(event: LogEvent) -> bool:
    # Timestamp included: each occurrence is seen exactly once (repeat counting for
    # Forge proposals), while the Hub re-serving the same row is still deduped.
    # Alert spam is prevented separately by the alert_worker cooldown.
    fingerprint = f"{event.timestamp}|{event.service}|{event.level}|{event.message}"
    with _seen_log_lock:
        if fingerprint in _seen_log_fingerprints:
            return False
        _seen_log_fingerprints.add(fingerprint)
        _seen_log_order.append(fingerprint)
        cache_size = cfg.get_int(cfg.SEEN_CACHE_SIZE, 500)
        while len(_seen_log_order) > cache_size:
            dropped = _seen_log_order.popleft()
            _seen_log_fingerprints.discard(dropped)
    return True


def _collect_new_log_events(service_name: str) -> list[LogEvent]:
    if cfg.get_str(cfg.LOG_SOURCE) == "docker":
        container_name = f"hestia_{service_name}"
        return docker_client.poll_container_logs(container_name, service_name)
    events = hub_client.fetch_service_log_events(
        service_name,
        level="WARNING",
        limit=cfg.get_int(cfg.HUB_LOG_LIMIT, 1),
    )
    return [event for event in events if _is_new_log_event(event)]


def _monitor_loop() -> None:
    # Brief startup pause so other services can initialise first.
    time.sleep(15)
    while True:
        try:
            _run_once()
        except Exception as exc:
            logger.error(
                "event=error_monitor_loop Error in monitor loop: %s", exc, exc_info=True)
        time.sleep(cfg.get_int(cfg.POLL_INTERVAL, 10))


def _check_provider_auth() -> None:
    """Discover auth-capable gateway services from Hub and verify their
    provider status.  Emits ``service.action_required`` events for any
    provider that is configured but not currently active.

    Service-agnostic — any service registered with the ``domain:auth_api``
    topology tag and a ``/api/gateway/auth/status`` endpoint is checked.
    """
    import requests as _req

    # 1) Discover auth-capable services via Hub topology tags
    try:
        registry_resp = _req.get(
            f"{hub_client.HUB_API_URL}/registry/services", timeout=6)
        if registry_resp.status_code != 200:
            logger.warning(
                "event=provider_auth_registry_fetch_failed status=%s",
                registry_resp.status_code)
            return
        all_services = (registry_resp.json() or {}).get("services") or []
    except Exception as exc:
        logger.warning("event=provider_auth_registry_fetch_error error=%s", exc)
        return

    auth_services: list[dict] = []
    for svc in all_services:
        if not isinstance(svc, dict):
            continue
        topology = svc.get("topology_tags") or []
        if not isinstance(topology, list):
            continue
        if "domain:auth_api" in topology:
            auth_services.append(svc)

    if not auth_services:
        return  # No auth-capable services registered — nothing to check

    # 2) Query each auth service's provider status
    for svc in auth_services:
        svc_name = str(svc.get("name", "")).strip()
        if not svc_name:
            continue
        try:
            resp = _req.post(
                f"{hub_client.HUB_API_URL}/route/{svc_name}/api/gateway/auth/status",
                json={
                    "method": "GET",
                    "headers": {},
                    "query": {},
                    "body": None,
                    "timeout_seconds": 8,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(
                    "event=provider_auth_check_non200 service=%s status=%s",
                    svc_name, resp.status_code)
                continue
            routed = resp.json() or {}
            status_code = int(routed.get("status_code", 500))
            if status_code >= 400:
                logger.warning(
                    "event=provider_auth_check_error service=%s status=%s",
                    svc_name, status_code)
                continue
            data = routed.get("payload") or {}
        except Exception as exc:
            logger.warning(
                "event=provider_auth_check_request_failed service=%s error=%s",
                svc_name, exc)
            continue

        # 3) Emit action_required events for configured-but-inactive providers
        providers = data.get("providers") or []
        runtime = data.get("runtime") or {}
        # Provider names differ between the env list and the runtime registry
        # ("microsoft" vs "outlook"): normalize, or Outlook is "broken" forever.
        _aliases = {"microsoft": "outlook", "outlook": "outlook", "google": "google"}
        active = {_aliases.get(str(a).lower(), str(a).lower()) for a in (runtime.get("active") or [])}
        for p in providers:
            if not isinstance(p, dict):
                continue
            p_name = str(p.get("provider", "")).strip()
            configured = bool(p.get("configured", False))
            if not configured or not p_name:
                continue
            if _aliases.get(p_name.lower(), p_name.lower()) in active:
                continue  # Already active

            _ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H")
            try:
                _req.post(
                    f"{hub_client.HUB_API_URL}/route/hermes/api/events/ingest",
                    json={
                        "method": "POST",
                        "headers": {},
                        "query": {},
                        "body": {
                            "event_type": "service.action_required",
                            "domain": "system",
                            "entity_id": f"argus-auth-{svc_name}-{p_name}-{_ts}",
                            "payload": {
                                "action": f"reauth_{p_name}",
                                "_message": (
                                    f"⚠️ <b>{p_name.title()}</b> su "
                                    f"<b>{svc_name.title()}</b> richiede "
                                    "riautenticazione. Usa il pulsante qui sotto."
                                ),
                                "_actions": [
                                    {
                                        "text": f"🔑 Riautentica {p_name.title()}",
                                        "command": f"gateway_auth_initiate_{p_name}",
                                    }
                                ],
                                "service": svc_name,
                                "source": "argus.provider_auth_check",
                            },
                        },
                        "timeout_seconds": 8,
                    },
                    timeout=10,
                )
            except Exception as exc:  # Hermes/Hub down must not abort the monitor cycle
                logger.warning("[🔄] event=argus_provider_auth_event_failed service=%s provider=%s error=%s",
                               svc_name, p_name, exc)
                continue
            logger.info(
                "event=argus_provider_auth_event_sent service=%s provider=%s",
                svc_name, p_name)


def _run_once() -> None:
    global _monitor_cycle_count
    t0 = time.perf_counter()
    logger.info("event=monitor_cycle_start")
    services = hub_client.discover_services()
    health = health_poller.poll_all(services)

    # --- Provider auth check (periodic) ---
    if cfg.get_bool(cfg.AUTH_CHECK_ENABLED):
        _monitor_cycle_count += 1
        if _monitor_cycle_count % cfg.get_int(cfg.AUTH_CHECK_EVERY, 1) == 0:
            _check_provider_auth()

    # --- Health alerts & recovery ---
    for name, report in health.items():
        with _unhealthy_lock:
            was_unhealthy = name in _unhealthy

        if report.status != "up":
            with _unhealthy_lock:
                _unhealthy[name] = report.status
            send_alert(
                ServiceAlert(
                    service=name,
                    kind="health",
                    level="CRITICAL" if report.status == "down" else "WARNING",
                    message=(
                        f"Service '{name}' is {report.status}. "
                        f"Error: {report.error or 'unknown'}"
                    ),
                )
            )
            if cfg.get_bool(cfg.REMEDIATE_ENABLED) and not was_unhealthy:
                dry_run = cfg.get_bool(cfg.REMEDIATE_DRY_RUN)
                ok, response = hub_client.request_hephaestus_remediation(
                    source="argus.monitor",
                    service=name,
                    issue=f"service_{report.status}",
                    severity="critical" if report.status == "down" else "warning",
                    requested_action="auto_health_recovery",
                    environment=cfg.get_str(cfg.REMEDIATE_ENVIRONMENT),
                    dry_run=dry_run,
                    auto_approve=False,
                    metadata={
                        "status": report.status,
                        "error": report.error,
                        "from_monitor_loop": True,
                    },
                )
                logger.info(
                    "event=argus_autoremediate_requested service=%s ok=%s dry_run=%s response=%s",
                    name,
                    ok,
                    dry_run,
                    str(response)[:250],
                )
                _plan_recheck(name, report.status, report.error)
        elif was_unhealthy:
            with _unhealthy_lock:
                _unhealthy.pop(name, None)
            _close_repair(name)
            send_recovery(name)

    # --- Incremental log polling + log alerts ---
    for svc in services:
        name = svc.get("name", "unknown")
        new_events = _collect_new_log_events(name)

        for event in new_events:
            due = forge_proposer.observe(event.service, event.level, event.message)
            if due:
                forge_proposer.propose(hub_client.HUB_API_URL, event.service, due)
            send_alert(
                ServiceAlert(
                    service=event.service,
                    kind="log",
                    level=event.level,
                    message=event.message,
                )
            )

    logger.info(
        "event=monitor_cycle_done ms=%d services_polled=%d",
        int((time.perf_counter() - t0) * 1000),
        len(services),
    )


def start() -> None:
    """Launch the monitoring loop in a daemon background thread."""
    if _agenda is not None and agenda_template is not None:
        _agenda.register_async([], templates=[agenda_template(
            "recheck", "Ricontrolla un servizio", service="argus", path="/api/argus/recheck/{service}",
            type="task", types=["task", "job"], icon="refresh",
            fields={"service": {"type": "string", "label": "Servizio", "in": "path", "description": "Nome del servizio (es. hecate)"}},
            required=["service"], title="Argus: ricontrolla {service}",
            description="Argus verifica la salute del servizio all'orario scelto e avvia la riparazione se serve.")])
    thread = threading.Thread(
        target=_monitor_loop,
        daemon=True,
        name="argus-monitor-loop",
    )
    thread.start()
    logger.info(
        "event=argus_monitor_loop_started interval_s=%s", cfg.get_int(cfg.POLL_INTERVAL, 10))

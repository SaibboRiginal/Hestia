"""Monitor service — background polling loop.

Each cycle (every ``ARGUS_POLL_INTERVAL`` seconds):
  1. Queries Hub for the current service registry.
  2. Polls each service's /health endpoint.
  3. Fetches only NEW log lines from each container (incremental cursor).
  4. Dispatches deduplicated alerts via Hermes for:
       - Health issues (down / degraded)
       - Log events at WARNING / ERROR / CRITICAL level
  5. Sends recovery notifications when a previously-alerted service comes back.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

from core import docker_client, health_poller, hub_client
from schemas.reports import LogEvent
from schemas.reports import ServiceAlert
from worker.alert_worker import send_alert, send_recovery

logger = logging.getLogger(f"hestia_argus.{__name__}")

POLL_INTERVAL = int(os.getenv("ARGUS_POLL_INTERVAL", "60"))
LOG_SOURCE = os.getenv("ARGUS_LOG_SOURCE", "hub").strip().lower()
HUB_LOG_LIMIT = int(os.getenv("ARGUS_HUB_LOG_LIMIT", "200"))
SEEN_CACHE_SIZE = max(500, int(os.getenv("ARGUS_LOG_SEEN_CACHE_SIZE", "5000")))

# Services currently known to be unhealthy — used to detect recovery.
# Value is the last known bad status string.
_unhealthy: dict[str, str] = {}
_unhealthy_lock = threading.Lock()
_seen_log_fingerprints: set[str] = set()
_seen_log_order: deque[str] = deque()
_seen_log_lock = threading.Lock()


def _is_new_log_event(event: LogEvent) -> bool:
    fingerprint = f"{event.service}|{event.level}|{event.message}"
    with _seen_log_lock:
        if fingerprint in _seen_log_fingerprints:
            return False
        _seen_log_fingerprints.add(fingerprint)
        _seen_log_order.append(fingerprint)
        while len(_seen_log_order) > SEEN_CACHE_SIZE:
            dropped = _seen_log_order.popleft()
            _seen_log_fingerprints.discard(dropped)
    return True


def _collect_new_log_events(service_name: str) -> list[LogEvent]:
    if LOG_SOURCE == "docker":
        container_name = f"hestia_{service_name}"
        return docker_client.poll_container_logs(container_name, service_name)
    events = hub_client.fetch_service_log_events(
        service_name,
        level="WARNING",
        limit=HUB_LOG_LIMIT,
    )
    return [event for event in events if _is_new_log_event(event)]


def _monitor_loop() -> None:
    # Brief startup pause so other services can initialise first.
    time.sleep(15)
    while True:
        try:
            _run_once()
        except Exception as exc:
            logger.error("event=error_monitor_loop Error in monitor loop: %s", exc, exc_info=True)
        time.sleep(POLL_INTERVAL)


def _run_once() -> None:
    services = hub_client.discover_services()
    health = health_poller.poll_all(services)

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
        elif was_unhealthy:
            with _unhealthy_lock:
                _unhealthy.pop(name, None)
            send_recovery(name)

    # --- Incremental log polling + log alerts ---
    for svc in services:
        name = svc.get("name", "unknown")
        new_events = _collect_new_log_events(name)

        for event in new_events:
            send_alert(
                ServiceAlert(
                    service=event.service,
                    kind="log",
                    level=event.level,
                    message=event.message,
                )
            )


def start() -> None:
    """Launch the monitoring loop in a daemon background thread."""
    thread = threading.Thread(
        target=_monitor_loop,
        daemon=True,
        name="argus-monitor-loop",
    )
    thread.start()
    logger.info("event=argus_monitor_loop_started_interval Argus monitor loop started (interval=%ss)", POLL_INTERVAL)

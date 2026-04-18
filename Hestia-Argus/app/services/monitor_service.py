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

from core import docker_client, health_poller, hub_client
from schemas.reports import ServiceAlert
from worker.alert_worker import send_alert, send_recovery

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("ARGUS_POLL_INTERVAL", "60"))

# Services currently known to be unhealthy — used to detect recovery.
# Value is the last known bad status string.
_unhealthy: dict[str, str] = {}
_unhealthy_lock = threading.Lock()


def _monitor_loop() -> None:
    # Brief startup pause so other services can initialise first.
    time.sleep(15)
    while True:
        try:
            _run_once()
        except Exception as exc:
            logger.error("Error in monitor loop: %s", exc, exc_info=True)
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
        container_name = f"hestia_{name}"
        new_events = docker_client.poll_container_logs(container_name, name)

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
    logger.info("Argus monitor loop started (interval=%ss)", POLL_INTERVAL)

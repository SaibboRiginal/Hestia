from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

import requests


def _deadline_from_timeout(timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None:
        return None
    if timeout_seconds <= 0:
        return None
    return time.time() + timeout_seconds


def hub_health_url(hub_api_url: str) -> str:
    """Return the Hub health endpoint from a Hub API base URL.

    Example:
    - http://hestia_hub:19001/api -> http://hestia_hub:19001/health
    - http://hestia_hub:19001 -> http://hestia_hub:19001/health
    """
    raw = (hub_api_url or "").strip()
    if not raw:
        return "/health"

    parsed = urlsplit(raw)
    path = (parsed.path or "").rstrip("/")
    # Accept base forms like /api, /health, or /api/health and normalize all to /health.
    if path.endswith("/api/health"):
        path = path[:-11]
    elif path.endswith("/api"):
        path = path[:-4]
    elif path.endswith("/health"):
        path = path[:-7]

    normalized = parsed._replace(path=f"{path}/health", query="", fragment="")
    return urlunsplit(normalized).rstrip("/")


def wait_for_http_ready(
    url: str,
    *,
    timeout_seconds: float | None = None,
    interval_seconds: float = 2.0,
    request_timeout_seconds: float = 3.0,
    logger: logging.Logger | None = None,
    description: str = "endpoint",
) -> bool:
    """Wait until an HTTP endpoint responds with 2xx.

    Returns True on success, False when a finite timeout is reached.
    """
    deadline = _deadline_from_timeout(timeout_seconds)
    while True:
        try:
            response = requests.get(url, timeout=request_timeout_seconds)
            if 200 <= response.status_code < 300:
                if logger:
                    logger.info(
                        "event=startup_dependency_ready_target Startup dependency ready | target=%s", description)
                return True
            if logger:
                logger.warning(
                    "event=startup_dependency_ready_yet_target Startup dependency not ready yet | target=%s status=%s",
                    description,
                    response.status_code,
                )
        except Exception as error:
            if logger:
                logger.warning(
                    "event=startup_dependency_check_failed_target Startup dependency check failed | target=%s error=%s",
                    description,
                    error,
                )

        if deadline is not None and time.time() >= deadline:
            if logger:
                logger.error("event=startup_wait_timed_out_target Startup wait timed out | target=%s", description)
            return False
        time.sleep(max(0.2, interval_seconds))


def wait_for_hub_services(
    hub_api_url: str,
    required_services: Iterable[str],
    *,
    timeout_seconds: float | None = None,
    interval_seconds: float = 2.0,
    request_timeout_seconds: float = 4.0,
    logger: logging.Logger | None = None,
) -> bool:
    """Wait until required services appear in Hub registry.

    Returns True on success, False when a finite timeout is reached.
    """
    normalized_required = {
        str(name).strip().lower()
        for name in required_services
        if str(name).strip()
    }
    if not normalized_required:
        return True

    endpoint = f"{hub_api_url.rstrip('/')}/registry/services"
    deadline = _deadline_from_timeout(timeout_seconds)

    while True:
        try:
            response = requests.get(endpoint, timeout=request_timeout_seconds)
            if 200 <= response.status_code < 300:
                payload = response.json() or {}
                services = payload.get("services") or []
                available = {
                    str(item.get("name", "")).strip().lower()
                    for item in services
                    if isinstance(item, dict)
                }
                missing = sorted(normalized_required - available)
                if not missing:
                    if logger:
                        logger.info(
                            "event=startup_dependencies_ready_hub_services Startup dependencies ready | hub_services=%s",
                            ",".join(sorted(normalized_required)),
                        )
                    return True
                if logger:
                    logger.warning(
                        "event=waiting_hub_services_missing Waiting for Hub services | missing=%s",
                        ",".join(missing),
                    )
            else:
                if logger:
                    logger.warning(
                        "event=hub_registry_probe_returned_non Hub registry probe returned non-success | status=%s",
                        response.status_code,
                    )
        except Exception as error:
            if logger:
                logger.warning("event=hub_registry_probe_failed Hub registry probe failed: %s", error)

        if deadline is not None and time.time() >= deadline:
            if logger:
                logger.error(
                    "event=startup_wait_timed_out_required_hub_services Startup wait timed out | required_hub_services=%s",
                    ",".join(sorted(normalized_required)),
                )
            return False
        time.sleep(max(0.2, interval_seconds))


def start_hub_keepalive(
    register: "Callable[[], object]",
    *,
    interval_seconds: float | None = None,
    logger: logging.Logger | None = None,
    name: str = "hub-keepalive",
) -> threading.Thread:
    """Re-register on Hub periodically (daemon thread).

    Hub keeps its registry in memory: after a Hub restart, a service that
    registered only once at startup disappears and every Hub-routed call to it
    fails.  Identical re-registrations are cheap "refreshes" on the Hub side
    (no registry event).  Interval: ``HUB_KEEPALIVE_SECONDS`` (default 60).
    """
    interval = float(interval_seconds or os.getenv("HUB_KEEPALIVE_SECONDS", "60"))
    log = logger or logging.getLogger("hestia_common.startup")

    def _loop() -> None:
        while True:
            time.sleep(max(5.0, interval))
            try:
                register()
            except Exception as exc:  # never kill the thread
                log.warning("[🔄] event=hub_keepalive_failed error=%s", exc)

    thread = threading.Thread(target=_loop, daemon=True, name=name)
    thread.start()
    return thread

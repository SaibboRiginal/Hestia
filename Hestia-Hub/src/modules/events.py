"""Registry event bus — revision tracking and webhook fan-out.

Single responsibility: manage the monotonically-increasing registry revision
counter and notify all interested services whenever the registry changes.
"""
from __future__ import annotations

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)


class RegistryEvents:
    """Tracks registry revision and fans out ``hub.registry.changed`` webhooks.

    Parameters
    ----------
    notify_timeout:
        Seconds to wait for each service webhook call (default: 2).
    """

    def __init__(self, notify_timeout: float = 2.0) -> None:
        self._revision: int = 0
        self._updated_at: float = time.time()
        self._notify_timeout = notify_timeout
        self._lock = threading.Lock()
        self._changed = threading.Condition(self._lock)

    # ── Read-only properties ──────────────────────────────────────────────────

    @property
    def revision(self) -> int:
        """Current registry revision counter (monotonically increasing)."""
        return self._revision

    @property
    def updated_at(self) -> float:
        """Unix timestamp of the last revision bump."""
        return self._updated_at

    # ── Public API ────────────────────────────────────────────────────────────

    def bump(self, services: list[dict], reason: str) -> None:
        """Increment the revision counter and fan-out webhooks asynchronously.

        Parameters
        ----------
        services:
            Snapshot of all currently registered services.
        reason:
            Human-readable reason string included in the webhook payload.
        """
        with self._lock:
            self._revision += 1
            self._updated_at = time.time()
            revision = self._revision
            updated_at = self._updated_at
            self._changed.notify_all()

        notify_thread = threading.Thread(
            target=self._notify_all,
            args=(services, reason, revision, updated_at),
            daemon=True,
        )
        notify_thread.start()

    def wait_for_change(self, after_revision: int, timeout_seconds: float) -> tuple[int, float, bool]:
        """Block until registry revision changes or timeout is reached.

        Returns tuple: (revision, updated_at, changed)
        """
        with self._changed:
            if self._revision > max(0, after_revision):
                return self._revision, self._updated_at, True

            timeout_value = max(0.0, float(timeout_seconds))
            self._changed.wait(timeout=timeout_value)
            changed = self._revision > max(0, after_revision)
            return self._revision, self._updated_at, changed

    # ── Private helpers ───────────────────────────────────────────────────────

    def _notify_all(
        self,
        services: list[dict],
        reason: str,
        revision: int,
        updated_at: float,
    ) -> None:
        """Fan out webhook POSTs to every service that advertises a webhook path."""
        payload = {
            "event": "hub.registry.changed",
            "reason": reason,
            "revision": revision,
            "updated_at": updated_at,
        }
        for service in services:
            capabilities = service.get("capabilities") or {}
            webhook_path = str(capabilities.get(
                "hub_events_webhook", "")).strip()
            if not webhook_path.startswith("/"):
                continue
            endpoint = f"{str(service.get('base_url', '')).rstrip('/')}{webhook_path}"
            try:
                requests.post(endpoint, json=payload,
                              timeout=self._notify_timeout)
            except requests.RequestException:
                logger.debug(
                    "[RegistryEvents] Notify failed | endpoint=%s", endpoint)

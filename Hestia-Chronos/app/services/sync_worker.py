"""Chronos sync worker — periodic Hecate Calendar → Archive sync."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from core import archive_client, hermes_client

logger = logging.getLogger("hestia_chronos.sync_worker")

# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

_ENABLED = os.getenv("CHRONOS_SYNC_ENABLED", "true").strip().lower() == "true"
_POLL_SECONDS = int(os.getenv("CHRONOS_SYNC_POLL_SECONDS", "900"))
_LOOK_BACK_DAYS = int(os.getenv("CHRONOS_SYNC_LOOK_BACK_DAYS", "1"))
_LOOK_AHEAD_DAYS = int(os.getenv("CHRONOS_SYNC_LOOK_AHEAD_DAYS", "30"))
_NOTIFY_NEW = os.getenv("CHRONOS_SYNC_NOTIFY_NEW",
                        "true").strip().lower() == "true"
_CALENDAR_ID = os.getenv("CHRONOS_SYNC_CALENDAR_ID", "primary")

# ─────────────────────────────────────────────────────────────────────────────
#  State
# ─────────────────────────────────────────────────────────────────────────────

# External IDs seen since the last container start.  Populated silently on the
# first tick so we don't spam notifications for pre-existing events.
_known_external_ids: set[str] = set()
_first_tick_done: bool = False
_state_lock = threading.Lock()

_HUB_API_URL = os.getenv(
    "HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")


def _format_event_notification(record: dict) -> str:
    """Build an HTML notification message for a new calendar event."""
    title = str((record or {}).get("title") or "Nuovo evento")
    start = str((record or {}).get("start_datetime") or "")
    end = str((record or {}).get("end_datetime") or "")
    location = str((record or {}).get("location") or "")
    provider = str((record or {}).get("provider") or "calendar")

    lines = [
        f"🆕 <b>Nuovo evento nel calendario</b>",
        f"<b>{title}</b>",
    ]
    if start:
        lines.append(f"🕐 {_format_dt(start)}")
    if end:
        lines.append(f"🕔 fine: {_format_dt(end)}")
    if location:
        lines.append(f"📍 {location}")
    html_link = (record or {}).get("html_link")
    if html_link:
        lines.append(
            f'<a href="{html_link}">Apri in {provider.capitalize()}</a>')
    return "\n".join(lines)


def _format_dt(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-d %B %Y, %H:%M")
    except Exception:
        return iso_str


def _is_future_event(record: dict) -> bool:
    """Return True if the event starts in the future (relevant for new-event notifications)."""
    try:
        start = datetime.fromisoformat(
            str((record or {}).get("start_datetime") or ""))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return start > datetime.now(timezone.utc)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Core tick
# ─────────────────────────────────────────────────────────────────────────────


def _tick() -> None:
    global _first_tick_done

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=_LOOK_BACK_DAYS)
    window_end = now + timedelta(days=_LOOK_AHEAD_DAYS)

    active = ["google", "outlook"]

    newly_seen: list = []

    for provider in active:
        envelope = {
            "method": "GET",
            "headers": {},
            "query": {
                "start_datetime": window_start.isoformat(),
                "end_datetime": window_end.isoformat(),
                "provider": provider,
                "calendar_id": _CALENDAR_ID,
                "max_results": 250,
            },
            "body": None,
            "timeout_seconds": 20,
        }
        try:
            response = requests.post(
                f"{_HUB_API_URL}/route/hecate/api/gateway/calendar/events",
                json=envelope,
                timeout=22,
            )
            response.raise_for_status()
            routed = response.json() if response.content else {}
            if int((routed or {}).get("status_code", 500)) >= 400:
                continue
            payload = (routed or {}).get("payload") or {}
            records = payload.get("events") if isinstance(
                payload, dict) else []
            if not isinstance(records, list):
                continue
        except Exception as exc:
            logger.warning(
                "event=sync_list_events_failed_provider [SYNC] list_events failed for provider=%s: %s", provider, exc)
            continue

        for record in records:
            ext_id = str((record or {}).get("event_id") or "")
            composite_key = f"{provider}:{ext_id}"

            with _state_lock:
                is_new = composite_key not in _known_external_ids
                _known_external_ids.add(composite_key)

            # Upsert into Archive (idempotent)
            archive_client.upsert_calendar_item(
                external_id=ext_id or None,
                source=provider,
                kind="event",
                title=(record or {}).get("title") or "Evento senza titolo",
                description=(record or {}).get("description"),
                start_at=(record or {}).get(
                    "start_datetime") or now.isoformat(),
                end_at=(record or {}).get("end_datetime"),
                all_day=False,
                location=(record or {}).get("location"),
                html_link=(record or {}).get("html_link"),
                nag_enabled=True,
            )

            # Queue notification candidates (skip on first tick to avoid spam)
            if is_new and _first_tick_done and _NOTIFY_NEW:
                if _is_future_event(record):
                    newly_seen.append(record)

    # Mark first tick as complete AFTER processing so that the first run
    # populates _known_external_ids silently.
    with _state_lock:
        if not _first_tick_done:
            _first_tick_done = True
            logger.info(
                "event=sync_first_tick_complete_event [SYNC] First tick complete — %d event(s) pre-loaded into known set",
                len(_known_external_ids),
            )
            return

    # Dispatch notifications for new events
    for record in newly_seen:
        msg = _format_event_notification(record)
        ok = hermes_client.publish_event(
            domain="calendar",
            event_type="calendar.sync",
            entity_id=str((record or {}).get("event_id") or ""),
            payload={
                "_message": msg,
                "title": (record or {}).get("title"),
                "provider": (record or {}).get("provider"),
            },
        )
        logger.info(
            "event=sync_new_event_notification_sent [SYNC] New-event notification sent=%s | provider=%s title=%r",
            ok,
            (record or {}).get("provider"),
            (record or {}).get("title"),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Worker loop
# ─────────────────────────────────────────────────────────────────────────────


def _run_loop() -> None:
    logger.info(
        "event=sync_worker_started_poll_every [SYNC] Worker started — poll every %ds | window -%dd to +%dd | notify_new=%s",
        _POLL_SECONDS,
        _LOOK_BACK_DAYS,
        _LOOK_AHEAD_DAYS,
        _NOTIFY_NEW,
    )
    while True:
        try:
            _tick()
        except Exception as exc:
            logger.error(
                "event=sync_unhandled_error_tick [SYNC] Unhandled error in tick: %s", exc)
        time.sleep(_POLL_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────


def start() -> None:
    """Start the sync worker in a daemon thread."""
    if not _ENABLED:
        logger.info(
            "event=sync_sync_worker_disabled_chronos_sync_enabled [SYNC] Sync worker disabled (CHRONOS_SYNC_ENABLED=false)")
        return
    t = threading.Thread(
        target=_run_loop, name="chronos-sync-worker", daemon=True)
    t.start()
    logger.info(
        "event=sync_daemon_thread_started [SYNC] Daemon thread started")

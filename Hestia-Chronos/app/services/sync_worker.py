"""Chronos sync worker — periodic Google/Outlook Calendar → Archive sync.

Background thread started at FastAPI startup.  Every CHRONOS_SYNC_POLL_SECONDS
(default 900 = 15 minutes) it:

  1. Fetches events from all active calendar providers for a configurable
     time window (CHRONOS_SYNC_LOOK_BACK_DAYS before now →
     CHRONOS_SYNC_LOOK_AHEAD_DAYS ahead of now).
  2. Upserts every event into Archive (idempotent — external_id deduplicates).
  3. If CHRONOS_SYNC_NOTIFY_NEW=true (default), dispatches a Hermes
     notification for each event that appears for the first time *and* starts
     in the future (i.e. not a historical back-fill item).

New-event detection:
  A module-level set (``_known_external_ids``) is populated on the very first
  sync tick.  On subsequent ticks, any ``external_id`` not yet in the set is
  treated as "new" and triggers a notification.  The set persists in memory
  for the lifetime of the process (cleared on container restart).  This means:
    • No notification spam after a container restart (first tick always
      populates the set silently).
    • New events added to Google Calendar between ticks generate a
      notification on the next tick.

Env vars (all optional):
  CHRONOS_SYNC_ENABLED           — "true" / "false" (default: "true")
  CHRONOS_SYNC_POLL_SECONDS      — int (default: 900)
  CHRONOS_SYNC_LOOK_BACK_DAYS    — int, days to fetch behind now (default: 1)
  CHRONOS_SYNC_LOOK_AHEAD_DAYS   — int, days to fetch ahead of now (default: 30)
  CHRONOS_SYNC_NOTIFY_NEW        — "true" / "false" (default: "true")
  CHRONOS_SYNC_CALENDAR_ID       — calendar id to query (default: "primary")
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import archive_client, hermes_client
from providers.registry import CalendarProviderRegistry

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

# Shared provider registry injected by main.py at startup.
_registry: Optional[CalendarProviderRegistry] = None


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _format_event_notification(record) -> str:
    """Build an HTML notification message for a new calendar event."""
    title = record.title or "Nuovo evento"
    start = record.start_datetime or ""
    end = record.end_datetime or ""
    location = record.location or ""
    provider = record.provider or "calendar"

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
    if record.html_link:
        lines.append(
            f'<a href="{record.html_link}">Apri in {provider.capitalize()}</a>')
    return "\n".join(lines)


def _format_dt(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-d %B %Y, %H:%M")
    except Exception:
        return iso_str


def _is_future_event(record) -> bool:
    """Return True if the event starts in the future (relevant for new-event notifications)."""
    try:
        start = datetime.fromisoformat(record.start_datetime or "")
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

    if _registry is None:
        logger.warning("[SYNC] Registry not injected — skipping tick")
        return

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=_LOOK_BACK_DAYS)
    window_end = now + timedelta(days=_LOOK_AHEAD_DAYS)

    active = _registry.active_providers
    if not active:
        logger.debug("[SYNC] No active providers — skipping tick")
        return

    newly_seen: list = []

    for provider in active:
        try:
            records = provider.list_events(
                start=window_start,
                end=window_end,
                calendar_id=_CALENDAR_ID,
                max_results=250,
            )
        except Exception as exc:
            logger.warning(
                "[SYNC] list_events failed for provider=%s: %s", provider.name, exc)
            continue

        for record in records:
            ext_id = record.event_id or ""
            composite_key = f"{provider.name}:{ext_id}"

            with _state_lock:
                is_new = composite_key not in _known_external_ids
                _known_external_ids.add(composite_key)

            # Upsert into Archive (idempotent)
            archive_client.upsert_calendar_item(
                external_id=ext_id or None,
                source=provider.name,
                kind="event",
                title=record.title or "Evento senza titolo",
                description=record.description,
                start_at=record.start_datetime or now.isoformat(),
                end_at=record.end_datetime,
                all_day=False,
                location=record.location,
                html_link=record.html_link,
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
                "[SYNC] First tick complete — %d event(s) pre-loaded into known set",
                len(_known_external_ids),
            )
            return

    # Dispatch notifications for new events
    for record in newly_seen:
        msg = _format_event_notification(record)
        ok = hermes_client.publish_event(
            domain="calendar",
            event_type="calendar.sync",
            entity_id=record.event_id or "",
            payload={"_message": msg, "title": record.title,
                     "provider": record.provider},
        )
        logger.info(
            "[SYNC] New-event notification sent=%s | provider=%s title=%r",
            ok,
            record.provider,
            record.title,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Worker loop
# ─────────────────────────────────────────────────────────────────────────────


def _run_loop() -> None:
    logger.info(
        "[SYNC] Worker started — poll every %ds | window -%dd to +%dd | notify_new=%s",
        _POLL_SECONDS,
        _LOOK_BACK_DAYS,
        _LOOK_AHEAD_DAYS,
        _NOTIFY_NEW,
    )
    while True:
        try:
            _tick()
        except Exception as exc:
            logger.error("[SYNC] Unhandled error in tick: %s", exc)
        time.sleep(_POLL_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────


def start(registry: CalendarProviderRegistry) -> None:
    """Start the sync worker in a daemon thread.

    Args:
        registry: The shared CalendarProviderRegistry instance from main.py.
    """
    global _registry
    if not _ENABLED:
        logger.info("[SYNC] Sync worker disabled (CHRONOS_SYNC_ENABLED=false)")
        return
    _registry = registry
    t = threading.Thread(
        target=_run_loop, name="chronos-sync-worker", daemon=True)
    t.start()
    logger.info("[SYNC] Daemon thread started")

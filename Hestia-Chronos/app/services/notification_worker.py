"""Chronos notification worker — proactive calendar reminders via Hermes.

Background thread started at FastAPI startup.  Every CHRONOS_NOTIFY_POLL_SECONDS
(default 300 = 5 minutes) it:

  1. Reads upcoming events from Archive for the next NOTIFY_LOOK_AHEAD_HOURS
     (default 26).
  2. For each event, determines which notification bucket applies:
       • "1d"  — event starts in ≤ 26h and > 2h 10m
       • "2h"  — event starts in ≤ 2h 10m and > 35m
       • "30m" — event starts in ≤ 35m and > 0m (i.e. hasn't passed yet)
  3. Sends a Hermes notification if that bucket hasn't been sent yet for
     this event (tracked via ``last_notified_bucket`` in Archive).
  4. Marks the bucket as sent in Archive.

Nag control:
  • ``nag_enabled=False`` on a CalendarItem suppresses all notifications.
  • The user can toggle nag via ``PATCH /api/calendar/items/{id}/nag`` on Archive,
    or by saying "stop nagging me about [event title]" to Oracle (which calls
    that endpoint).  A future preference store will allow domain-level rules.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from core import archive_client, hermes_client

logger = logging.getLogger("hestia_chronos.notification_worker")

# ─────────────────────────────────────────────────────────────────────────────
#  Configuration (from env)
# ─────────────────────────────────────────────────────────────────────────────

_POLL_SECONDS = int(os.getenv("CHRONOS_NOTIFY_POLL_SECONDS", "300"))
_LOOK_AHEAD_HOURS = float(os.getenv("NOTIFY_LOOK_AHEAD_HOURS", "26"))

# Bucket thresholds in minutes (upper boundary — lower boundary is the next bucket)
_BUCKET_30M_MAX_MINUTES = 35.0
_BUCKET_2H_MAX_MINUTES = 130.0     # 2h 10m
_BUCKET_1D_MAX_MINUTES = _LOOK_AHEAD_HOURS * 60

_BUCKET_LABELS = {
    "30m": "30 minuti",
    "2h": "2 ore",
    "1d": "domani",
}

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _determine_bucket(minutes_until: float) -> str | None:
    """Return the notification bucket for an event starting ``minutes_until`` minutes from now."""
    if minutes_until <= 0:
        return None   # already started
    if minutes_until <= _BUCKET_30M_MAX_MINUTES:
        return "30m"
    if minutes_until <= _BUCKET_2H_MAX_MINUTES:
        return "2h"
    if minutes_until <= _BUCKET_1D_MAX_MINUTES:
        return "1d"
    return None


def _format_datetime(iso_str: str) -> str:
    """Return a human-readable Italian date/time string."""
    try:
        dt = datetime.fromisoformat(iso_str)
        # Express in Europe/Rome local time (UTC+1/+2 depending on DST).
        # We keep it simple: just display as-is from the stored tz-aware string.
        return dt.strftime("%-d %B %Y, %H:%M")
    except Exception:
        return iso_str


def _build_notification(item: dict, bucket: str) -> str:
    """Build an HTML notification message for a calendar event."""
    label = _BUCKET_LABELS.get(bucket, bucket)
    title = item.get("title", "Evento")
    start = item.get("start_at", "")
    location = item.get("location") or ""
    description = item.get("description") or ""
    kind_icons = {"event": "🗓️", "task": "✅", "reminder": "⏰"}
    icon = kind_icons.get(item.get("kind", "event"), "🗓️")

    lines = [
        f"{icon} <b>Promemoria — tra {label}</b>",
        f"<b>{title}</b>",
    ]
    if start:
        lines.append(f"🕐 {_format_datetime(start)}")
    if location:
        lines.append(f"📍 {location}")
    if description:
        snippet = description[:200].strip()
        if len(description) > 200:
            snippet += "…"
        lines.append(f"\n{snippet}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
#  Worker loop
# ─────────────────────────────────────────────────────────────────────────────


def _run_loop() -> None:
    logger.info(
        "event=notify_worker_started_poll_every [NOTIFY] Worker started — poll every %ds, look-ahead %.0fh",
        _POLL_SECONDS,
        _LOOK_AHEAD_HOURS,
    )
    while True:
        try:
            _tick()
        except Exception as exc:
            logger.error("event=notify_unhandled_error_tick [NOTIFY] Unhandled error in tick: %s", exc)
        time.sleep(_POLL_SECONDS)


def _tick() -> None:
    now = datetime.now(timezone.utc)
    look_ahead = now + timedelta(hours=_LOOK_AHEAD_HOURS)

    items = archive_client.list_upcoming(
        from_time=now.isoformat(),
        to_time=look_ahead.isoformat(),
        nag_enabled=True,
        limit=500,
    )

    if not items:
        logger.debug("event=notify_upcoming_nag_enabled_items [NOTIFY] No upcoming nag-enabled items found")
        return

    sent = 0
    for item in items:
        start_iso = item.get("start_at")
        if not start_iso:
            continue

        try:
            start_dt = datetime.fromisoformat(start_iso)
        except ValueError:
            continue

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        minutes_until = (start_dt - now).total_seconds() / 60.0
        bucket = _determine_bucket(minutes_until)
        if bucket is None:
            continue

        last_bucket = item.get("last_notified_bucket")
        # Priority order: "30m" > "2h" > "1d"
        bucket_priority = {"30m": 3, "2h": 2, "1d": 1}
        if last_bucket and bucket_priority.get(last_bucket, 0) >= bucket_priority.get(bucket, 0):
            # Already sent this bucket or a more urgent one — skip.
            continue

        message = _build_notification(item, bucket)
        event_payload = {**item, "_message": message, "_bucket": bucket}
        ok = hermes_client.publish_event(
            domain="calendar",
            event_type="calendar.reminder",
            entity_id=str(item.get("id", "")),
            payload=event_payload,
        )
        if ok:
            archive_client.mark_notified(item["id"], bucket)
            sent += 1
            logger.info(
                "event=notify_sent_bucket_item_id_title [NOTIFY] Sent bucket=%s for item_id=%s title=%r",
                bucket,
                item["id"],
                item.get("title", ""),
            )
        else:
            logger.warning(
                "event=notify_failed_send_bucket_item_id [NOTIFY] Failed to send bucket=%s for item_id=%s",
                bucket,
                item["id"],
            )

    if sent:
        logger.info("event=notify_tick_complete_notification_sent [NOTIFY] Tick complete — %d notification(s) sent", sent)


# ─────────────────────────────────────────────────────────────────────────────
#  Public start helper
# ─────────────────────────────────────────────────────────────────────────────


def start() -> None:
    """Start the notification worker in a daemon thread."""
    t = threading.Thread(
        target=_run_loop, name="chronos-notify-worker", daemon=True)
    t.start()
    logger.info("event=notify_daemon_thread_started [NOTIFY] Daemon thread started")

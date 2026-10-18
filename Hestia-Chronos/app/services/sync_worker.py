"""Chronos sync worker — periodic Hecate Calendar → Archive sync.

Driven by the agenda job ``chronos.calendar_sync`` (its recurrence = how often; paused by the user = no
sync, not even at boot). Window, calendar id and new-event notices are Themis settings read each sync.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from core import archive_client, hermes_client
from core import chronos_settings as CS

logger = logging.getLogger("hestia_chronos.sync_worker")

# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Code default of the agenda job recurrence (the user edits it in the agenda; that edit wins).
_DEFAULT_INTERVAL_SECONDS = 900


def _int_setting(key: str, fallback: int) -> int:
    try:
        return max(0, int(CS.settings.get(key)))
    except (TypeError, ValueError):
        return fallback

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

    t0 = time.perf_counter()
    logger.info("event=sync_tick_start")

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=_int_setting(CS.SYNC_LOOK_BACK_DAYS, 1))
    window_end = now + timedelta(days=max(1, _int_setting(CS.SYNC_LOOK_AHEAD_DAYS, 30)))
    calendar_id = str(CS.settings.get(CS.SYNC_CALENDAR_ID) or "primary").strip() or "primary"
    notify_new = bool(CS.settings.get(CS.SYNC_NOTIFY_NEW))

    active = ["google", "outlook"]

    newly_seen: list = []
    events_upserted = 0

    for provider in active:
        envelope = {
            "method": "GET",
            "headers": {},
            "query": {
                "start_datetime": window_start.isoformat(),
                "end_datetime": window_end.isoformat(),
                "provider": provider,
                "calendar_id": calendar_id,
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
            events_upserted += 1
            archive_client.upsert_calendar_item(
                external_id=ext_id or None,
                source=provider,
                kind="event",
                title=(record or {}).get("title") or "Evento senza titolo",
                description=(record or {}).get("description"),
                start_at=(record or {}).get(
                    "start_datetime") or now.isoformat(),
                end_at=(record or {}).get("end_datetime"),
                # Providers return a bare date (YYYY-MM-DD) for all-day events.
                all_day=len(str((record or {}).get("start_datetime") or "")) == 10,
                location=(record or {}).get("location"),
                html_link=(record or {}).get("html_link"),
                nag_enabled=True,
            )

            # Queue notification candidates (skip on first tick to avoid spam)
            if is_new and _first_tick_done and notify_new:
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
            logger.info(
                "event=sync_tick_done ms=%d events_upserted=%d new_events=%d",
                int((time.perf_counter() - t0) * 1000),
                events_upserted,
                len(newly_seen),
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

    logger.info(
        "event=sync_tick_done ms=%d events_upserted=%d new_events=%d",
        int((time.perf_counter() - t0) * 1000),
        events_upserted,
        len(newly_seen),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Worker loop
# ─────────────────────────────────────────────────────────────────────────────


AGENDA_JOB_KEY = "chronos.calendar_sync"
_tick_lock = threading.Lock()
_last_run_ts = 0.0


def run_sync(trigger: str = "api") -> dict:
    """One sync at a time (agenda job, fallback loop, maintenance, user)."""
    global _last_run_ts
    if not _tick_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        _last_run_ts = time.time()
        _tick()
        return {"status": "ok", "trigger": trigger}
    except Exception as exc:
        logger.error("[🔄] event=sync_tick_failed trigger=%s error=%s", trigger, exc)
        return {"status": "error", "trigger": trigger, "error": str(exc)[:300]}
    finally:
        _tick_lock.release()


def agenda_rules() -> list[dict]:
    """Calendar sync as a recurring job of the assistant agenda (fired via Hub)."""
    minutes = max(1, _DEFAULT_INTERVAL_SECONDS // 60)
    return [{
        "key": AGENDA_JOB_KEY, "type": "job", "title": "Chronos: sincronizza calendari",
        "description": "Importa gli eventi da Google/Outlook (via Hecate) e avvisa dei nuovi.",
        "start_at": "2026-01-01T00:00:00", "recurrence": f"FREQ=MINUTELY;INTERVAL={minutes}",
        "action": {"service": "chronos", "path": "/api/calendar/sync", "method": "POST",
                   "body": {"trigger": "agenda"}, "timeout_seconds": 20},
        "params": {"interval_seconds": _DEFAULT_INTERVAL_SECONDS},
    }]


_FREQ_SECONDS = {"MINUTELY": 60, "HOURLY": 3600, "DAILY": 86400}


def _interval_seconds(item: dict | None) -> int:
    """Sync interval = recurrence of the agenda job (user edits win), else the code default."""
    rule = str((item or {}).get("recurrence") or "").upper()
    freq = re.search(r"FREQ=(MINUTELY|HOURLY|DAILY)", rule)
    if not freq:
        return _DEFAULT_INTERVAL_SECONDS
    interval = re.search(r"INTERVAL=(\d+)", rule)
    return _FREQ_SECONDS[freq.group(1)] * max(1, int(interval.group(1)) if interval else 1)


def _job() -> dict | None:
    from services import agenda as assistant_agenda
    try:
        return assistant_agenda.get(AGENDA_JOB_KEY)
    except Exception:
        return None                       # missing or Archive down


def _user_stopped(item: dict | None) -> bool:
    """Paused/cancelled by the user = no calendar sync (no fallback)."""
    return bool(item) and item.get("status") in {"paused", "cancelled", "completed"}


def _agenda_driving(item: dict | None = None) -> bool:
    """True when the agenda job exists and is handled (or paused by the user)."""
    item = item if item is not None else _job()
    if not item:
        return False                      # missing or Archive down → fallback
    if _user_stopped(item):
        return True                       # user decision: do not self-run
    last = item.get("last_fired")
    if not last:
        return True
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(last).replace("Z", "+00:00"))
           ).total_seconds()
    return age <= 3 * _interval_seconds(item)


def _run_loop() -> None:
    """Boot sync + agenda registration; then fallback only if the agenda is not driving."""
    from services import agenda as assistant_agenda
    logger.info(
        "event=sync_worker_started_poll_every [SYNC] Worker started — agenda job %s | window -%dd to +%dd | notify_new=%s",
        AGENDA_JOB_KEY,
        _int_setting(CS.SYNC_LOOK_BACK_DAYS, 1),
        _int_setting(CS.SYNC_LOOK_AHEAD_DAYS, 30),
        bool(CS.settings.get(CS.SYNC_NOTIFY_NEW)),
    )
    registered = False
    if _user_stopped(_job()):
        logger.info("event=sync_startup_skipped reason=agenda_job_paused")
    else:
        run_sync("startup")
    while True:
        time.sleep(60)
        if not registered:
            try:
                assistant_agenda.register_rules("chronos", agenda_rules())
                registered = True
            except Exception as exc:
                logger.warning("[🔄] event=sync_agenda_register_failed error=%s", exc)
        try:
            if time.time() - _last_run_ts >= _DEFAULT_INTERVAL_SECONDS and not _agenda_driving():
                logger.info("[🔄] event=sync_fallback_run reason=agenda_not_driving")
                run_sync("fallback")
        except Exception as exc:
            logger.error("[🔄] event=sync_fallback_loop_error error=%s", exc)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────


def start() -> None:
    """Start the sync worker in a daemon thread (pause the agenda job to stop syncing)."""
    t = threading.Thread(
        target=_run_loop, name="chronos-sync-worker", daemon=True)
    t.start()
    logger.info(
        "event=sync_daemon_thread_started [SYNC] Daemon thread started")

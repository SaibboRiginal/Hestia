"""Smart calendar assistant (brainstorm B8, dossier docs/work/2026-10-24-tutto-brainstorm-cindy).

Looks at the owner's own events (every source but the assistant's agenda) of the next days and, where two timed
events overlap, **proposes** to move the later one to the first free slot of the same day — never moves anything by
itself (R4). The proposal is a Hermes card «Sposta alle 15:30» (→ the provider update through Hecate) / «Lascia così».
Deterministic, no model call. Agenda job ``chronos.smart_calendar`` (daily, movable/pausable) or by hand (tool
``calendar_check``). The same pair is proposed once (dedupe key per pair and day).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from core import archive_client, hermes_client, life_store
from core import chronos_settings as CS
from services import agenda

logger = logging.getLogger("hestia_chronos.smart_calendar")

DAY_START, DAY_END = 8, 21        # free slots are looked for inside the owner's day
_kept: set[str] = set()           # «Lascia così»: that event is not proposed again (Archive chronos-store)


def load_kept() -> int:
    for row in life_store.load("smart_kept", limit=1000):
        _kept.add(str(row.get("id")))
    return len(_kept)


def keep(event_id: str) -> dict:
    _kept.add(str(event_id))
    life_store.put("smart_kept", str(event_id), {"event_id": str(event_id)},
                   at=datetime.now(_tz()).isoformat())
    logger.info("event=smart_calendar_kept event_id=%s", event_id)
    return {"ok": True, "kept": str(event_id)}


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(agenda._TZ_DEFAULT)
    except Exception:
        return ZoneInfo("Europe/Rome")


def _dt(value: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=_tz())).astimezone(_tz())


def _timed(items: list[dict]) -> list[dict]:
    out = []
    for i in items:
        if i.get("source") == agenda.SOURCE or i.get("all_day") or str(i.get("status") or "") == "cancelled":
            continue
        start, end = _dt(i.get("start_at")), _dt(i.get("end_at"))
        if not start or not end or end <= start or (end - start) >= timedelta(hours=20):
            continue
        out.append({**i, "_start": start, "_end": end})
    return sorted(out, key=lambda e: e["_start"])


def _gap() -> timedelta:
    try:
        return timedelta(minutes=int(CS.settings.get(CS.FLEX_GAP) or 0))
    except Exception:
        return timedelta(0)


def free_slot(events: list[dict], day_events: list[dict], duration: timedelta, after: datetime) -> datetime | None:
    """First start ≥ ``after`` on the same day where ``duration`` fits between the other events (+ gap)."""
    gap = _gap()
    candidate = after + gap
    day_end = after.replace(hour=DAY_END, minute=0, second=0, microsecond=0)
    for e in sorted(day_events, key=lambda x: x["_start"]):
        if e["_end"] + gap <= candidate:
            continue
        if e["_start"] - gap >= candidate + duration:
            break
        candidate = max(candidate, e["_end"] + gap)
    if candidate.hour < DAY_START:
        candidate = candidate.replace(hour=DAY_START, minute=0)
    minute = (candidate.minute + 14) // 15 * 15        # round up to the quarter
    candidate = candidate.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    return candidate if candidate + duration <= day_end else None


def conflicts(items: list[dict]) -> list[dict]:
    events = _timed(items)
    out = []
    for i, a in enumerate(events):
        for b in events[i + 1:]:
            if b["_start"] >= a["_end"]:
                break
            later = b if b["_start"] >= a["_start"] else a
            other = a if later is b else b
            day = [e for e in events if e["_start"].date() == later["_start"].date() and e is not later]
            slot = free_slot(events, day, later["_end"] - later["_start"], max(other["_end"], later["_start"]))
            out.append({"move": later, "keep": other, "to": slot})
    return out


def _source_id(item: dict) -> tuple[str, str]:
    provider = str(item.get("source") or "google")
    event_id = str(item.get("external_id") or item.get("event_id") or item.get("id") or "")
    return provider, event_id


def check(days: int = 3, now: datetime | None = None) -> dict:
    now = now or datetime.now(_tz())
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    items = archive_client.list_items(from_time=start.isoformat(), to_time=(start + timedelta(days=days)).isoformat(),
                                      limit=300)
    proposals = []
    for c in conflicts(items):
        move, keep, to = c["move"], c["keep"], c["to"]
        if move["_start"] < now:
            continue
        provider, event_id = _source_id(move)
        if not event_id or event_id in _kept:
            continue
        when = move["_start"].strftime("%d/%m %H:%M")
        text = (f"<b>{move.get('title')}</b> ({when}) si sovrappone a <b>{keep.get('title')}</b> "
                f"({keep['_start'].strftime('%H:%M')}–{keep['_end'].strftime('%H:%M')}).")
        actions = []
        if to:
            dur = move["_end"] - move["_start"]
            text += f"\nPosso spostarlo alle {to.strftime('%H:%M')}."
            actions.append({"id": "move", "label": f"Sposta alle {to.strftime('%H:%M')}", "style": "primary",
                            "service": "chronos", "method": "PATCH", "path": f"/api/calendar/events/{event_id}",
                            "body": {"provider": provider, "calendar_id": str(move.get("calendar_id") or "primary"),
                                     "updates": {"start_datetime": to.isoformat(),
                                                 "end_datetime": (to + dur).isoformat()}}})
        else:
            text += "\nQuel giorno non trovo un buco libero: decidi tu."
        actions.append({"id": "keep", "label": "Lascia così", "service": "chronos", "method": "POST",
                        "path": "/api/calendar/smart/kept", "body": {"event_id": event_id}})
        key = f"smart_calendar:{event_id}:{move['_start'].date().isoformat()}:{keep.get('external_id') or keep.get('id')}"
        hermes_client.publish_event("calendar", "service.action_required", f"smart.{event_id}", {
            "_title": "Due impegni si sovrappongono", "_message": text, "_source": "Calendario",
            "_level": "warning", "dedupe_key": key, "_actions": actions,
            "_link": {"module": "chronos", "page": "agenda"}})
        proposals.append({"event": move.get("title"), "with": keep.get("title"),
                          "to": to.isoformat() if to else None})
    logger.info("event=smart_calendar_checked days=%d items=%d proposals=%d", days, len(items), len(proposals))
    return {"checked": len(items), "proposals": proposals}

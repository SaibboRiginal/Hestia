"""Weather on the calendar page (dossier docs/work/2026-10-20-meteo-hecate §3.7).

For the visible range (only the next ``HORIZON_DAYS`` days: past days and far days get nothing) the page gets:
- ``days``: Casa's weather per day (min–max, condition, rain hours) — the chip next to the day number;
- ``events``: the weather at the place and hour of located agenda occurrences the page sends
  (``params.place`` of an item, e.g. a planned run);
- ``external``: Marko's own calendar events (Google/Outlook through Hecate) that have a location, with the weather
  there at their hour. They are only shown, never modified.
One Hecate call (``weather/at``) answers all of it; Hecate caches the forecast. Failures answer empty parts.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Callable

logger = logging.getLogger("hestia_chronos.agenda_weather")

HORIZON_DAYS = 14
_EXT_TTL = 600
_ext_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_lock = threading.Lock()

Route = Callable[..., tuple[int, dict]]


def _day(value: str) -> date | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _external(route: Route, start: date, end: date) -> list[dict]:
    """Located events of the provider calendars in [start, end] (cached a few minutes)."""
    key = (start.isoformat(), end.isoformat())
    with _lock:
        hit = _ext_cache.get(key)
    if hit and time.time() - hit[0] < _EXT_TTL:
        return hit[1]
    try:
        status, payload = route(method="GET", path="/api/gateway/calendar/events", timeout_seconds=15,
                                query={"start_datetime": f"{start.isoformat()}T00:00:00+00:00",
                                       "end_datetime": f"{(end + timedelta(days=1)).isoformat()}T00:00:00+00:00",
                                       "max_results": 250})
    except Exception as exc:
        logger.warning("[🔄] event=agenda_weather_events_failed error=%s fallback=no_external", exc)
        return []
    rows = []
    if status < 400:
        for e in (payload or {}).get("events") or []:
            loc = str(e.get("location") or "").strip()
            if loc and e.get("start_datetime") and "://" not in loc:     # skip video-call links
                rows.append({"id": f"{e.get('provider')}:{e.get('event_id')}", "title": e.get("title") or "",
                             "start": e["start_datetime"], "location": loc})
    with _lock:
        _ext_cache[key] = (time.time(), rows)
    return rows


def build(route: Route, start: str, end: str, located: list[dict] | None = None, *,
          today: date | None = None, with_external: bool = True) -> dict:
    """``located``: ``[{key, place, at}]`` sent by the page for its own occurrences with a place."""
    today = today or datetime.now().date()
    s, e = _day(start) or today, _day(end) or today
    lo, hi = max(s, today), min(e, today + timedelta(days=HORIZON_DAYS - 1))
    out: dict = {"days": {}, "events": {}, "external": [], "horizon": HORIZON_DAYS}
    if lo > hi:
        return out
    items: list[dict] = []
    d = lo
    while d <= hi:
        items.append({"key": f"day:{d.isoformat()}", "date": d.isoformat()})
        d += timedelta(days=1)
    for row in (located or [])[:100]:
        when = _day(row.get("at") or "")
        if row.get("key") and row.get("place") and when and lo <= when <= hi:
            items.append({"key": f"ev:{row['key']}", "place": str(row["place"]), "at": str(row["at"])})
    ext = _external(route, lo, hi) if with_external else []
    for x in ext:
        items.append({"key": f"ext:{x['id']}", "place": x["location"], "at": x["start"]})
    try:
        status, payload = route(method="POST", path="/api/gateway/weather/at", body={"items": items}, timeout_seconds=12)
    except Exception as exc:
        logger.warning("[🔄] event=agenda_weather_failed error=%s fallback=no_weather", exc)
        return out
    answers = (payload or {}).get("items") or {} if status < 400 else {}
    for key, a in answers.items():
        if not isinstance(a, dict) or a.get("status") != "ok":
            continue
        if key.startswith("day:"):
            out["days"][key[4:]] = a.get("day")
        elif key.startswith("ev:"):
            out["events"][key[3:]] = {"place": a.get("place"), "day": a.get("day"), "hour": a.get("hour")}
    for x in ext:
        a = answers.get(f"ext:{x['id']}")
        if isinstance(a, dict) and a.get("status") == "ok":
            out["external"].append({**x, "place": a.get("place"), "hour": a.get("hour"), "day": a.get("day")})
    logger.info("event=agenda_weather_built days=%s events=%s external=%s", len(out["days"]), len(out["events"]),
                len(out["external"]))
    return out

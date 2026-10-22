"""«Mentre non c'ero» — what the agenda missed while the assistant could not answer (oracle-offline v3 D).

When ``chat.reply`` relaxes from ``queued`` to ``live`` (the «Non disponibile» overlay ends), Chronos — owner of the
agenda — looks at the runs that failed in that window: each job/task still active is run again once if its missed
run is recent enough (``chronos.catchup.max_age_hours``), older ones are only listed. Then ONE message through
Hermes says what happened: «Mentre non c'ero: …». Nothing missed → nothing sent. Fixed text (no model round trip
right after a recovery).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from core import chronos_settings as CS
from core import hermes_client
from services import agenda

logger = logging.getLogger("hestia_chronos.catchup")

NOTICE_EVENT = "service.action_required"   # the system subscription every client always has
_INACTIVE = {"cancelled", "completed", "paused"}


def _ts(value: str) -> datetime:
    at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _duration(seconds: float) -> str:
    minutes = max(1, int(round(seconds / 60)))
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h {minutes % 60} min"


def missed(since: datetime, now: datetime | None = None) -> list[dict]:
    """Latest failed agenda run per item in the window, unless a later run of the same item went fine."""
    now = now or datetime.now(timezone.utc)
    rows = agenda.runs(since=since, limit=500, now=now)["runs"]           # newest first
    seen: set[str] = set()
    out = []
    for r in rows:
        item = str(r["item_id"])
        if item in seen:
            continue
        seen.add(item)            # newest run of this item decides
        if r["status"] != "failed" or r["by"] not in (None, "agenda") or r["item_status"] in _INACTIVE:
            continue
        out.append(r)
    return out


def _max_age_hours() -> int:
    try:
        return max(0, int(CS.settings.get(CS.CATCHUP_MAX_AGE)))
    except (TypeError, ValueError):
        return 6


def run(since: datetime | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    max_age = timedelta(hours=_max_age_hours())
    # Chronos restarted during the outage: no start known → the last max-age window (at least 1 h).
    window_start = since or now - max(max_age, timedelta(hours=1))
    redone, still_failed, too_old = [], [], []
    for r in missed(window_start, now):
        if now - _ts(r["at"]) > max_age:
            too_old.append(r["title"])
            continue
        try:
            ok = bool(agenda.run_now(r["item_id"], by="catchup").get("ok"))
        except Exception as exc:
            logger.warning("[🔄] event=catchup_run_failed item=%s error=%s", r["key"], exc)
            ok = False
        (redone if ok else still_failed).append(r["title"])
    result = {"since": window_start.isoformat(), "redone": redone, "failed": still_failed, "too_old": too_old}
    logger.info("event=catchup_done redone=%d failed=%d too_old=%d", len(redone), len(still_failed), len(too_old))
    if redone or still_failed or too_old:
        hermes_client.publish_event("assistant", NOTICE_EVENT, "assistant.catchup", {
            "_message": message(now - window_start, redone, still_failed, too_old), "_title": "Mentre non c'ero",
            "_level": "info", "_source": "chronos", "redone": redone, "failed": still_failed, "too_old": too_old})
    return result


def message(away: timedelta, redone: list[str], failed: list[str], too_old: list[str]) -> str:
    lines = [f"🕒 <b>Mentre non c'ero</b> ({_duration(away.total_seconds())}):"]
    if redone:
        lines.append("• recuperato ora: " + ", ".join(redone))
    if failed:
        lines.append("• ancora non riuscito: " + ", ".join(failed) + " (riprovo con l'agenda)")
    if too_old:
        lines.append("• saltato, troppo vecchio per rifarlo: " + ", ".join(too_old))
    return "\n".join(lines)

"""Weekly coach plan — Chronos side (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §5–§6).

Chronos asks every service with the Hub tag ``coach`` what it needs (``GET /api/coach/needs``), places the needs in
the user's free time with the generic planner (``coach_planner``), stores the plan as assistant-agenda items and
tells each module where its needs landed. Oracle only writes the weekly text; Hermes delivers it.

Plan items: agenda ``event`` items, ``owner`` = the module, key ``coach.<week>.<module>.<need_id>.<date>``, parent
``coach.week.<week>`` (``<week>`` = ISO date of the first day). ``params.coach_status``: planned · done · skipped ·
replanned. Items the user moved (``user_modified``) are never moved back.

Contract for ``count``: a module reports how many are **still to do** from ``start`` (the first day planned), so
done things are already out of it; Chronos keeps only the future items the user moved.

Re-plans are pushed: a module report (done/skipped/changed), a calendar sync that brings an event over a block,
a chat request. A short debounce coalesces bursts; nothing polls.
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from core import archive_client
from core import chronos_settings as CS
from core import hermes_client
from services import agenda
from services import coach_planner as planner

logger = logging.getLogger("hestia_chronos.coach")

OWNER = "chronos"
JOB_KEY = "chronos.coach_week"
USE_CASE = "chronos.coach"          # declared in the Hub registration (core/hub_client.py)
HUB_TAG = "coach"
NOTICE_WEEK = "coach.week"
NOTICE_CHANGE = "coach.change"
_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
_DEBOUNCE_SECONDS = 5.0
WEEKDAYS = planner.WEEKDAYS
_lock = threading.RLock()
_pending: dict[str, Any] = {"timer": None, "reasons": []}


class CoachError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── time helpers ────────────────────────────────────────────────────────────


def tz() -> ZoneInfo:
    return ZoneInfo(agenda._TZ_DEFAULT)


def now() -> datetime:
    return datetime.now(tz())


def _cfg(key: str, default: Any) -> Any:
    try:
        value = CS.settings.get(key)
        return default if value in (None, "") else value
    except Exception:
        return default


def _hhmm(value: Any, default: time) -> time:
    try:
        return time.fromisoformat(str(value)[:5])
    except ValueError:
        return default


def week_start_index() -> int:
    return 6 if str(_cfg("themis.personal.week_start", "monday")).lower() == "sunday" else 0


def week_of(day: date) -> tuple[date, date]:
    start = day - timedelta(days=(day.weekday() - week_start_index()) % 7)
    return start, start + timedelta(days=7)


def week_id(start: date) -> str:
    return start.isoformat()


def _item_day(item: dict) -> date | None:
    try:
        return datetime.fromisoformat(str(item.get("start_at")).replace("Z", "+00:00")).astimezone(tz()).date()
    except (TypeError, ValueError):
        return None


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=tz())).astimezone(tz())


def day_label(d: date, today: date | None = None) -> str:
    today = today or now().date()
    if d == today:
        return "oggi"
    if d == today + timedelta(days=1):
        return "domani"
    return WEEKDAYS[d.weekday()]


# ── Hub ─────────────────────────────────────────────────────────────────────


def _route(service: str, method: str, path: str, *, query: dict | None = None, body: dict | None = None,
           timeout: float = 15) -> tuple[int, Any]:
    resp = requests.post(f"{_HUB}/route/{service}/{path.lstrip('/')}",
                         json={"method": method, "headers": {}, "query": query or {}, "body": body,
                               "timeout_seconds": timeout}, timeout=timeout + 3)
    resp.raise_for_status()
    routed = resp.json() if resp.content else {}
    return int(routed.get("status_code", 500)), routed.get("payload")


def coaches() -> list[str]:
    """Services registered on Hub with the tag ``coach``."""
    try:
        resp = requests.get(f"{_HUB}/registry/services", timeout=5)
        resp.raise_for_status()
        services = (resp.json() or {}).get("services") or []
    except Exception as exc:
        logger.warning("[🔄] event=coach_discovery_failed error=%s", exc)
        return []
    return sorted({str(s.get("name")) for s in services if HUB_TAG in (s.get("tags") or []) and s.get("name")})


def gather(start: date, end: date) -> list[dict]:
    """Needs of every coach for ``[start, end)``. A module that does not answer is listed with ``ok: False``."""
    out = []
    for svc in coaches():
        try:
            status, payload = _route(svc, "GET", "api/coach/needs",
                                     query={"start": start.isoformat(), "end": end.isoformat()})
            if status >= 400 or not isinstance(payload, dict):
                raise RuntimeError(f"status {status}")
            out.append({"module": payload.get("module") or svc, "service": svc, "label": payload.get("label") or svc,
                        "domain": payload.get("domain") or "", "state": payload.get("state") or "",
                        "needs": payload.get("needs") or [], "ok": True})
        except Exception as exc:
            logger.warning("[🔄] event=coach_needs_failed service=%s error=%s fallback=keep_last_plan", svc, exc)
            out.append({"module": svc, "service": svc, "label": svc, "domain": "", "state": "", "needs": [],
                        "ok": False})
    return out


def _fit(services: dict[str, str]):
    def ask(module: str, need_id: str, day: date, minutes: int) -> dict | None:
        try:
            status, payload = _route(services.get(module, module), "POST", "api/coach/fit",
                                     body={"need_id": need_id, "date": day.isoformat(), "minutes": minutes})
            return payload if status < 400 and isinstance(payload, dict) else None
        except Exception as exc:
            logger.warning("[🔄] event=coach_fit_failed module=%s need=%s error=%s", module, need_id, exc)
            return None
    return ask


# ── busy time ───────────────────────────────────────────────────────────────


def busy(start: date, end: date) -> dict[date, list[tuple[datetime, datetime]]]:
    """User calendar events (Archive, synced from Google/Outlook) + busy blocks added for the plan.
    All-day events do not block (birthdays, reminders); a whole day away is a busy block («mercoledì via»)."""
    lo = datetime.combine(start, time(0), tzinfo=tz())
    hi = datetime.combine(end, time(0), tzinfo=tz())
    out: dict[date, list[tuple[datetime, datetime]]] = {}
    spans: list[tuple[datetime, datetime]] = []
    for ev in archive_client.list_items(from_time=lo.isoformat(), to_time=hi.isoformat(), limit=500):
        if ev.get("source") == agenda.SOURCE or ev.get("all_day") or str(ev.get("status") or "") == "cancelled":
            continue
        s, e = _local(ev.get("start_at")), _local(ev.get("end_at"))
        if s and (not e or e <= s):
            e = s + timedelta(hours=1)
        if s and e:
            spans.append((s, e))
    for item in agenda.list_items(owner=OWNER):
        if not (item.get("params") or {}).get("coach_busy"):
            continue
        s, e = _local(item.get("start_at")), _local(item.get("end_at"))
        if s and e and e > lo and s < hi:
            spans.append((s, e))
    for s, e in spans:
        d = s.date()
        while d <= e.date():
            if start <= d < end:
                out.setdefault(d, []).append((s, e))
            d += timedelta(days=1)
    return out


# ── plan items ──────────────────────────────────────────────────────────────


def plan_items(week: str) -> list[dict]:
    return [i for i in agenda.list_items(include_cancelled=True)
            if (i.get("params") or {}).get("coach") and (i.get("params") or {}).get("week") == week]


def _parent_key(week: str) -> str:
    return f"coach.week.{week}"


def _key(week: str, module: str, need_id: str, d: date) -> str:
    return f"coach.{week}.{module}.{need_id}.{d.isoformat()}"


def _status(item: dict) -> str:
    return (item.get("params") or {}).get("coach_status") or "planned"


def _live(item: dict) -> bool:
    return item.get("status") not in ("cancelled",) and _status(item) in ("planned", "done")


def _keep(items: list[dict], first_day: date) -> list[dict]:
    """Future items the user moved (count towards the module's still-to-do) and done ones of the planned days
    (they occupy time; the module already left them out of ``count``)."""
    keep = []
    for i in items:
        d = _item_day(i)
        if not d or d < first_day or not _live(i):
            continue
        p = i.get("params") or {}
        done = _status(i) == "done"
        if not (done or i.get("user_modified")):
            continue
        s, e = _local(i.get("start_at")), _local(i.get("end_at"))
        keep.append({"module": i["owner"], "need_id": p.get("need_id") or "", "kind": p.get("kind") or "block",
                     "title": i.get("title") or "", "date": d, "start": i.get("start_at") or "",
                     "start_dt": s, "end_dt": e, "tags": p.get("tags") or [],
                     "not_same_day": p.get("not_same_day") or [], "counts": not done,
                     "minutes": p.get("minutes") or 0, "key": i["key"]})
    return keep


def _planner_cfg() -> planner.PlannerConfig:
    return planner.PlannerConfig(max_blocks_per_day=int(_cfg(CS.COACH_MAX_BLOCKS, 2)),
                                 max_minutes_per_day=int(_cfg(CS.COACH_MAX_MINUTES, 120)),
                                 buffer_minutes=int(_cfg(CS.COACH_BUFFER, 15)))


def wet_hours(days: list[dict], zone) -> dict[date, list[tuple[datetime, datetime]]]:
    """Hecate forecast days (hourly) → hours with rain (≥50% or ≥0.5 mm) or dark, per day (outdoor rule)."""
    out: dict[date, list[tuple[datetime, datetime]]] = {}
    for d in days or []:
        for h in d.get("hours") or []:
            try:
                s = datetime.fromisoformat(str(h["time"])).replace(tzinfo=zone)
            except (KeyError, ValueError):
                continue
            if (h.get("rain_prob") or 0) >= 50 or (h.get("rain_mm") or 0) >= 0.5 or h.get("is_day") is False:
                out.setdefault(s.date(), []).append((s, s + timedelta(hours=1)))
    return out


def _wet(start: date, end: date) -> dict[date, list[tuple[datetime, datetime]]]:
    """Rainy/dark hours at home for ``outdoor`` needs (Hecate weather). Unreachable → no filter."""
    try:
        status, payload = _route("hecate", "GET", "api/gateway/weather/forecast", timeout=10, query={
            "date_from": start.isoformat(), "date_to": (end - timedelta(days=1)).isoformat(), "hourly": "true"})
    except Exception as exc:
        logger.warning("[🔄] event=coach_weather_failed error=%s fallback=no_outdoor_filter", exc)
        return {}
    if status >= 400 or (payload or {}).get("status") != "ok":
        logger.info("event=coach_weather_skipped status=%s", (payload or {}).get("status") or status)
        return {}
    return wet_hours(payload.get("days") or [], tz())


def _free(days: list[date], busy_map: dict, current: datetime) -> dict[date, list]:
    """Free intervals per day: the plan window minus the user's events (with the buffer); today from now on."""
    day_start = _hhmm(_cfg(CS.COACH_DAY_START, "07:00"), time(7))
    day_end = _hhmm(_cfg(CS.COACH_DAY_END, "22:00"), time(22))
    buffer = int(_cfg(CS.COACH_BUFFER, 15))
    free = {}
    for d in days:
        spans = planner.free_intervals(d, day_start, day_end, busy_map.get(d, []), tz(), buffer)
        if d == current.date():
            spans = [(max(s, current), e) for s, e in spans if e > current]
        free[d] = spans
    return free


def replan(day: date | None = None, *, reason: str = "manual", week_start: date | None = None) -> dict:
    """Place every coach's needs from ``day`` (default today) to the end of its week."""
    with _lock:
        current = now()
        first = max(day or current.date(), current.date())
        start, end = week_of(week_start or first)
        first = max(first, start)
        week = week_id(start)
        days = [first + timedelta(days=i) for i in range((end - first).days)]
        modules = gather(first, end)
        services = {m["module"]: m["service"] for m in modules}
        unreachable = {m["module"] for m in modules if not m["ok"]}
        existing = plan_items(week)
        before = {i["key"]: i for i in existing if _live(i)}
        keep = _keep(existing, first)
        avoid = {(i["owner"], (i.get("params") or {}).get("need_id") or "", _item_day(i)) for i in existing
                 if _status(i) == "skipped" and _item_day(i) and _item_day(i) >= first}
        needs = [{**n, "module": m["module"]} for m in modules if m["ok"] for n in m["needs"]]
        wet = _wet(first, end) if any("outdoor" in (n.get("tags") or []) for n in needs) else {}
        result = planner.plan_week(days, _free(days, busy(first, end), current), needs, keep=keep, avoid=avoid,
                                   cfg=_planner_cfg(), tz=tz(), fit=_fit(services), wet=wet)
        _ensure_parent(week, start, end)
        written: set[str] = {k["key"] for k in keep}
        labels = {m["module"]: m["label"] for m in modules}
        domains = {m["module"]: m["domain"] for m in modules}
        for it in result["items"]:
            key, n = _key(week, it["module"], it["need_id"], it["date"]), 1
            while key in written:              # a kept item (moved by the user) already holds this day's key
                n += 1
                key = f"{_key(week, it['module'], it['need_id'], it['date'])}.{n}"
            written.add(key)
            params = {"coach": True, "week": week, "kind": it["kind"], "need_id": it["need_id"],
                      "domain": domains.get(it["module"], ""), "label": labels.get(it["module"], it["module"]),
                      "minutes": it["minutes"], "variant": it.get("variant"), "reason": it.get("reason") or "",
                      "link": it.get("link") or "", "tags": it.get("tags") or [],
                      "not_same_day": it.get("not_same_day") or [], "time_of_day": it.get("time_of_day"),
                      "priority": it.get("priority"), "coach_status": "planned"}
            old = before.get(key)
            if old and old.get("start_at") and _local(old["start_at"]) == _local(it["start"]) \
                    and (old.get("params") or {}).get("minutes") == it["minutes"] and _status(old) == "planned":
                continue                       # unchanged: no write
            agenda.create(title=it["title"], type_="event", owner=it["module"], start_at=it["start"],
                          end_at=it.get("end"), key=key, params=params, created_by=OWNER,
                          parent=_parent_key(week),
                          description=(it.get("variant") or {}).get("note") or it.get("reason") or "")
        moved = []
        for key, old in before.items():
            if key in written or old["owner"] in unreachable or _status(old) == "done":
                continue
            d = _item_day(old)
            if d and d < first:
                continue                       # the past stays as it was
            agenda.update(key, {"status": "cancelled",
                                "params": {**(old.get("params") or {}), "coach_status": "replanned"}}, by=OWNER)
            moved.append(old)
        summary = {"week": week, "start": start.isoformat(), "end": end.isoformat(), "updated_at": current.isoformat(),
                   "reason": reason,
                   "unplaced": [{**u, "label": labels.get(u["module"], u["module"]), "domain": domains.get(u["module"], "")}
                                for u in result["unplaced"]],
                   "targets": [{**t, "label": labels.get(t["module"], t["module"]), "domain": domains.get(t["module"], "")}
                               for t in result["targets"]],
                   "states": [{"module": m["module"], "label": m["label"], "state": m["state"], "ok": m["ok"]}
                              for m in modules]}
        _update_parent(week, summary)
        _tell_modules(week, services, unreachable)
        if reason not in ("weekly", "manual", "chat"):
            _notify_changes(moved, result["items"], before, current.date())
        logger.info("event=coach_replanned week=%s reason=%s items=%d unplaced=%d modules=%d",
                    week, reason, len(result["items"]), len(result["unplaced"]), len(modules))
        return view(week_start=start)


def _ensure_parent(week: str, start: date, end: date) -> None:
    try:
        agenda.get(_parent_key(week))
    except agenda.AgendaError:
        agenda.create(title="Piano della settimana", type_="event", owner=OWNER,
                      start_at=datetime.combine(start, time(0), tzinfo=tz()).isoformat(),
                      end_at=datetime.combine(end, time(0), tzinfo=tz()).isoformat(),
                      key=_parent_key(week), params={"coach_week": True, "week": week}, created_by=OWNER)


def _update_parent(week: str, summary: dict) -> None:
    item = agenda.get(_parent_key(week))
    agenda.update(item["key"], {"params": {**(item.get("params") or {}), **summary}}, by=OWNER)


def _tell_modules(week: str, services: dict[str, str], skip: set[str]) -> None:
    by_module: dict[str, list[dict]] = {}
    for i in plan_items(week):
        if _live(i):
            p = i.get("params") or {}
            by_module.setdefault(i["owner"], []).append(
                {"need_id": p.get("need_id"), "key": i["key"], "start_at": i.get("start_at"), "end_at": i.get("end_at"),
                 "kind": p.get("kind") or "block", "status": _status(i)})
    for module, svc in services.items():
        if module in skip:
            continue
        try:
            _route(svc, "POST", "api/coach/placed", body={"week": week, "items": by_module.get(module, [])})
        except Exception as exc:
            logger.warning("[🔄] event=coach_placed_failed module=%s error=%s", module, exc)


def _notify_changes(moved: list[dict], items: list[dict], before: dict, today: date) -> None:
    """One live notice when a re-plan changed something of today or tomorrow the user did not move."""
    soon = {today, today + timedelta(days=1)}
    lines = []
    for old in moved:
        d = _item_day(old)
        if d not in soon:
            continue
        p = old.get("params") or {}
        new = next((i for i in items if i["module"] == old["owner"] and i["need_id"] == p.get("need_id")
                    and _key(p.get("week"), i["module"], i["need_id"], i["date"]) not in before), None)
        when = _local(old.get("start_at"))
        if new:
            at = _local(new["start"])
            lines.append(f"{old['title']}: da {day_label(d, today)} {when:%H:%M} a {day_label(new['date'], today)}"
                         + (f" {at:%H:%M}" if new["kind"] == "block" else ""))
        else:
            lines.append(f"{old['title']} di {day_label(d, today)}: non entra più questa settimana")
    if not lines:
        return
    _deliver(NOTICE_CHANGE, "Piano aggiornato", "Ho cambiato il piano: " + "; ".join(lines) + ".")


def _deliver(key: str, title: str, text: str) -> bool:
    from hestia_common.reminders import reminder_event
    body = reminder_event(module=OWNER, domain="coach", key=key, title=title, text=text, actions=[],
                          page="settimana")
    return hermes_client.publish_event(body["domain"], body["event_type"], body["entity_id"], body["payload"])


# ── views ───────────────────────────────────────────────────────────────────


def _item_view(i: dict) -> dict:
    p = i.get("params") or {}
    return {"key": i["key"], "id": i.get("id"), "module": i["owner"], "label": p.get("label") or i["owner"],
            "domain": p.get("domain") or "", "title": i.get("title"), "kind": p.get("kind") or "block", "need_id": p.get("need_id"),
            "date": (_item_day(i) or date.today()).isoformat(), "start_at": i.get("start_at"),
            "end_at": i.get("end_at"), "minutes": p.get("minutes"), "status": _status(i),
            "moved_by_user": bool(i.get("user_modified")), "variant": p.get("variant"),
            "reason": p.get("reason") or "", "link": p.get("link") or "", "time_of_day": p.get("time_of_day")}


def view(day: date | None = None, *, week_start: date | None = None) -> dict:
    """The week's plan: items by day, targets, unplaced, each coach's state line."""
    start, end = week_of(week_start or day or now().date())
    week = week_id(start)
    items = [_item_view(i) for i in plan_items(week) if i["status"] != "cancelled" or _status(i) == "skipped"]
    items = [i for i in items if i["status"] in ("planned", "done", "skipped")]
    items.sort(key=lambda i: (i["start_at"] or "", i["module"], i["title"] or ""))
    try:
        meta = agenda.get(_parent_key(week)).get("params") or {}
    except agenda.AgendaError:
        meta = {}
    days = []
    for n in range((end - start).days):
        d = start + timedelta(days=n)
        days.append({"date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()],
                     "items": [i for i in items if i["date"] == d.isoformat()]})
    busy_blocks = [{"key": i["key"], "title": i.get("title"), "start_at": i.get("start_at"), "end_at": i.get("end_at")}
                   for i in agenda.list_items(owner=OWNER) if (i.get("params") or {}).get("coach_busy")
                   and start <= (_item_day(i) or start) < end]
    return {"week": week, "start": start.isoformat(), "end": end.isoformat(), "planned": bool(meta.get("updated_at")),
            "updated_at": meta.get("updated_at"), "days": days, "targets": meta.get("targets") or [],
            "unplaced": meta.get("unplaced") or [], "states": meta.get("states") or [],
            "text": meta.get("text") or "", "busy": busy_blocks,
            "counts": {s: sum(1 for i in items if i["status"] == s) for s in ("planned", "done", "skipped")}}


def today_items(day: date | None = None) -> list[dict]:
    d = day or now().date()
    plan = view(d)
    return next((x["items"] for x in plan["days"] if x["date"] == d.isoformat()), [])


# ── weekly run ──────────────────────────────────────────────────────────────


def reviews(start: date, end: date) -> list[dict]:
    out = []
    for svc in coaches():
        try:
            status, payload = _route(svc, "GET", "api/coach/review",
                                     query={"start": start.isoformat(), "end": end.isoformat()})
            if status < 400 and isinstance(payload, dict):
                out.append(payload)
        except Exception as exc:
            logger.warning("[🔄] event=coach_review_failed service=%s error=%s", svc, exc)
    return out


def fixed_text(plan: dict, past: list[dict]) -> str:
    """The weekly message without the brain (Oracle down): short, readable aloud."""
    parts = []
    for d in plan["days"]:
        blocks = [i for i in d["items"] if i["kind"] == "block" and i["status"] == "planned"]
        if blocks:
            parts.append(d["weekday"][:3] + " " + ", ".join(f"{_local(i['start_at']):%H:%M} {i['title']}" for i in blocks))
    text = "Piano della settimana: " + ("; ".join(parts) if parts else "niente con un orario") + "."
    if plan["unplaced"]:
        text += " Non entra: " + "; ".join(f"{u['title']} ({u['reason']})" for u in plan["unplaced"][:3]) + "."
    done = [r for r in past if r.get("done") or r.get("missed")]
    if done:
        text += " Settimana passata: " + ", ".join(f"{r.get('label')} {r.get('done')} fatti" for r in done[:3]) + "."
    return text


def _prompt(plan: dict, past: list[dict]) -> str:
    lines = ["Sei l'assistente personale. Scrivi il messaggio del piano della settimana, in italiano, max 6 righe,",
             "tono caldo e pratico, niente emoji, niente nomi di moduli o di sistemi. Solo testo.",
             "PIANO:"]
    for d in plan["days"]:
        for i in d["items"]:
            when = _local(i["start_at"])
            lines.append(f"- {d['weekday']} {when:%H:%M} {i['title']} ({i['label']})"
                         + (f" versione corta {i['minutes']}'" if i.get("variant") else ""))
    for u in plan["unplaced"]:
        lines.append(f"NON ENTRA: {u['title']} — {u['reason']}")
    for t in plan["targets"]:
        lines.append(f"OBIETTIVO: {t['title']} {t.get('reason') or ''}")
    for s in plan["states"]:
        if s.get("state"):
            lines.append(f"STATO {s['label']}: {s['state']}")
    for r in past:
        lines.append(f"SETTIMANA PASSATA {r.get('label')}: fatti {r.get('done')}, saltati {r.get('missed')}"
                     + (f", {'; '.join(r.get('notes') or [])}" if r.get("notes") else ""))
    return "\n".join(lines)


def _brain_text(prompt: str, timeout: float = 60) -> str:
    status, payload = _route("oracle", "POST", "api/llm/generate", body={"prompt": prompt, "use_case": USE_CASE},
                             timeout=timeout)
    if status >= 400:
        raise RuntimeError(f"oracle status {status}")
    text = payload.get("response") or payload.get("raw") if isinstance(payload, dict) else payload
    return str(text or "").strip()


def run_week(day: date | None = None) -> dict:
    """Agenda job ``chronos.coach_week``: plan the coming week, write the text, deliver it."""
    target = (day or now().date()) + timedelta(days=1)
    plan = replan(target, reason="weekly", week_start=week_of(target)[0])
    start = date.fromisoformat(plan["start"])
    past = reviews(start - timedelta(days=7), start)
    try:
        text = _brain_text(_prompt(plan, past)) or fixed_text(plan, past)
    except Exception as exc:
        logger.warning("[🔄] event=coach_text_fallback error=%s", exc)
        text = fixed_text(plan, past)
    item = agenda.get(_parent_key(plan["week"]))
    agenda.update(item["key"], {"params": {**(item.get("params") or {}), "text": text, "reviews": past}}, by=OWNER)
    delivered = _deliver(NOTICE_WEEK, "La tua settimana", text)
    logger.info("event=coach_week_delivered week=%s delivered=%s", plan["week"], delivered)
    return {**plan, "text": text, "delivered": delivered}


# ── reports, chat actions ───────────────────────────────────────────────────


def schedule_replan(reason: str, day: date | None = None) -> None:
    """Coalesce bursts of reports (finish + check-in + …) into one re-plan a few seconds later."""
    with _lock:
        _pending["reasons"].append(reason)
        if _pending["timer"] is not None:
            return

        def _go():
            with _lock:
                reasons, _pending["reasons"], _pending["timer"] = _pending["reasons"], [], None
            try:
                replan(day, reason=reasons[0] if len(set(reasons)) == 1 else "changes")
            except Exception as exc:
                logger.warning("[🔄] event=coach_replan_failed reasons=%s error=%s", ",".join(reasons), exc)

        timer = threading.Timer(_DEBOUNCE_SECONDS, _go)
        timer.daemon = True
        _pending["timer"] = timer
        timer.start()


def _match(module: str, need_id: str, at: datetime) -> dict | None:
    week = week_id(week_of(at.date())[0])
    cands = [i for i in plan_items(week) if i["owner"] == module and _status(i) == "planned" and _live(i)
             and ((i.get("params") or {}).get("need_id") == need_id
                  or str((i.get("params") or {}).get("need_id") or "").startswith(need_id + "."))
             and _item_day(i) == at.date()]
    return sorted(cands, key=lambda i: abs((_local(i["start_at"]) - at).total_seconds()))[0] if cands else None


def report(module: str, event: str, need_id: str = "", at: str | None = None, reason: str = "") -> dict:
    """A module tells what happened: ``done`` / ``skipped`` (with ``need_id``) or ``changed``."""
    if event not in ("done", "skipped", "changed"):
        raise CoachError("event must be done, skipped or changed")
    when = _local(at) or now()
    if event == "changed":
        schedule_replan("changed")
        return {"ok": True, "replan": True}
    if not need_id:
        raise CoachError("need_id is required")
    item = _match(module, need_id, when)
    if item is None:
        schedule_replan(event)            # something not in the plan: the rest of the week may change
        return {"ok": True, "matched": None, "replan": True}
    status = "done" if event == "done" else "skipped"
    changes: dict[str, Any] = {"params": {**(item.get("params") or {}), "coach_status": status,
                                          "reported_at": when.isoformat(), "report_reason": reason[:200]}}
    if status == "done":
        changes["status"] = "completed"
    else:
        changes["status"] = "cancelled"
    agenda.update(item["key"], changes, by=OWNER)
    if status == "skipped":
        schedule_replan("skipped")
    return {"ok": True, "matched": item["key"], "status": status, "replan": status == "skipped"}


def move(ref: str, start_at: str, end_at: str | None = None) -> dict:
    """The user moves a plan item (WebUI drag or chat): it becomes theirs and is never moved back."""
    item = agenda.get(ref)
    if not (item.get("params") or {}).get("coach"):
        raise CoachError("not a plan item", 404)
    new_start = _local(start_at)
    if new_start is None:
        raise CoachError("start_at must be ISO 8601")
    old_day = _item_day(item)
    changes: dict[str, Any] = {"start_at": new_start.isoformat()}
    if end_at:
        changes["end_at"] = end_at
    moved = agenda.update(item["key"], changes, by="user")
    schedule_replan("moved", min(old_day or new_start.date(), new_start.date()))
    return _item_view(moved)


def skip(ref: str, reason: str = "") -> dict:
    item = agenda.get(ref)
    p = item.get("params") or {}
    if not p.get("coach"):
        raise CoachError("not a plan item", 404)
    agenda.update(item["key"], {"status": "cancelled", "params": {**p, "coach_status": "skipped",
                                                                  "report_reason": reason[:200]}}, by="user")
    schedule_replan("skipped")
    return {"ok": True, "key": item["key"], "status": "skipped"}


def add_busy(start_at: str, end_at: str, title: str = "") -> dict:
    """A period the plan must leave free («mercoledì sono via tutto il giorno»)."""
    s, e = _local(start_at), _local(end_at)
    if not s or not e or e <= s:
        raise CoachError("start_at and end_at must be ISO 8601 with end after start")
    item = agenda.create(title=title or "Impegno", type_="event", owner=OWNER, start_at=s.isoformat(),
                         end_at=e.isoformat(), key=f"coach.busy.{uuid.uuid4().hex[:10]}",
                         params={"coach_busy": True}, created_by="user")
    schedule_replan("busy", s.date())
    return {"key": item["key"], "title": item["title"], "start_at": item["start_at"], "end_at": item["end_at"]}


def remove_busy(ref: str) -> dict:
    item = agenda.get(ref)
    if not (item.get("params") or {}).get("coach_busy"):
        raise CoachError("not a busy block", 404)
    agenda.cancel(item["key"], by="user")
    schedule_replan("busy", _item_day(item))
    return {"ok": True, "key": item["key"]}


def on_calendar_synced(day: date | None = None) -> bool:
    """After a calendar sync: re-plan only when a user event now overlaps a planned block of this week."""
    current = now()
    start, end = week_of(day or current.date())
    blocks = [i for i in plan_items(week_id(start)) if _status(i) == "planned" and _live(i)
              and (i.get("params") or {}).get("kind") == "block" and not i.get("user_modified")
              and (_local(i.get("start_at")) or current) >= current]
    if not blocks:
        return False
    busy_map = busy(current.date(), end)
    buffer = timedelta(minutes=int(_cfg(CS.COACH_BUFFER, 15)))
    for b in blocks:
        s, e = _local(b["start_at"]), _local(b.get("end_at"))
        if not s or not e:
            continue
        if any(bs - buffer < e and be + buffer > s for bs, be in busy_map.get(s.date(), [])):
            schedule_replan("calendar")
            return True
    return False


def week_job_rule() -> dict:
    """``chronos.coach_week``: the evening before the week starts, 18:00 (user can move or pause it)."""
    from hestia_common.agenda_client import job_rule
    day = "SU" if week_start_index() == 0 else "SA"
    return job_rule(JOB_KEY, "Piano della settimana", service="chronos", path="/api/agenda/coach/week/run",
                    recurrence=f"FREQ=WEEKLY;BYDAY={day};BYHOUR=18;BYMINUTE=0",
                    start_at="2026-01-04T18:00:00",
                    description="La sera prima della settimana preparo il piano con i tuoi impegni e te lo mando. "
                                "Sposta o metti in pausa per cambiarlo.", timeout_seconds=180)


def started_at_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

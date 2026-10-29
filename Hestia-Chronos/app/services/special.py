"""Special events (brainstorm B6, dossier docs/work/2026-10-24-tutto-brainstorm-cindy §2.4).

A special moment is an assistant-agenda ``event`` (owner ``chronos``, key ``special.<…>``) with
``params.special = {kind: birthday | anniversary | custom, lead_days, person_id?, person?, note?}``; birthdays and
anniversaries repeat every year (``FREQ=YEARLY``). Sources:

- the owner's birthday from the personal setting ``themis.personal.birth_date`` (kept in sync, the owner's edits win);
- the owner, by hand (calendar, chat tool ``special_add``) — **manual**;
- the assistant, which discovers them in mails, conversations or memory and only **proposes** them
  (``special_propose`` → Hermes card «Aggiungi» / «No»); other modules (Persone) register people dates — **automatic**.

The daily job ``chronos.special.daily`` (``POST /api/special/run``) sends the lead-time notice ``lead_days`` before
(«Tra 7 giorni: compleanno di Anna»), and on the day the greeting plus the ``special_moment`` push to every Hub
service declaring ``capabilities.special_moment_endpoint`` (effects, gift ideas) and to routines waiting for it.
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from core import hermes_client
from services import agenda

logger = logging.getLogger("hestia_chronos.special")

_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
OWNER = "chronos"
PREFIX = "special."
KINDS = ("birthday", "anniversary", "custom")
KIND_LABEL = {"birthday": "Compleanno", "anniversary": "Anniversario", "custom": "Evento importante"}
BIRTH_KEY = "special.birthday.owner"
BIRTH_SETTING = "themis.personal.birth_date"
DEFAULT_LEAD = 7


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(agenda._TZ_DEFAULT)
    except Exception:
        return ZoneInfo("Europe/Rome")


def _today() -> date:
    return datetime.now(_tz()).date()


def _parse_day(value: Any) -> date:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise agenda.AgendaError("date must be YYYY-MM-DD") from exc


def _slug(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "evento")[:40]


def special_of(item: dict) -> dict:
    return dict((item.get("params") or {}).get("special") or {})


def next_on(item: dict, today: date | None = None) -> date | None:
    """Next day of the moment (today included)."""
    today = today or _today()
    try:
        first = datetime.fromisoformat(str(item["start_at"])).astimezone(_tz()).date()
    except (KeyError, ValueError):
        return None
    if not item.get("recurrence"):
        return first if first >= today else None
    for year in (today.year, today.year + 1):
        try:
            day = first.replace(year=year)
        except ValueError:                      # 29 February → 28 in other years
            day = first.replace(year=year, day=28)
        if day >= today:
            return day
    return None


def list_special(today: date | None = None) -> list[dict]:
    out = []
    for item in agenda.list_items(owner=OWNER):
        sp = special_of(item)
        if not sp or not str(item.get("key") or "").startswith(PREFIX):
            continue
        nxt = next_on(item, today)
        out.append({"key": item["key"], "title": item["title"], "kind": sp.get("kind") or "custom",
                    "kind_label": KIND_LABEL.get(sp.get("kind"), "Evento importante"),
                    "lead_days": int(sp.get("lead_days") if sp.get("lead_days") is not None else DEFAULT_LEAD),
                    "person": sp.get("person"), "person_id": sp.get("person_id"), "note": sp.get("note"),
                    "source": sp.get("source") or "utente", "yearly": bool(item.get("recurrence")),
                    "next": nxt.isoformat() if nxt else None,
                    "in_days": (nxt - (today or _today())).days if nxt else None, "status": item["status"]})
    return sorted(out, key=lambda s: (s["in_days"] is None, s["in_days"] if s["in_days"] is not None else 0))


def add(*, title: str, day: str, kind: str = "custom", lead_days: int | None = None, person: str = "",
        person_id: str = "", note: str = "", yearly: bool | None = None, source: str = "utente",
        key: str = "", by: str = "user") -> dict:
    kind = kind if kind in KINDS else "custom"
    first = _parse_day(day)
    yearly = (kind in ("birthday", "anniversary")) if yearly is None else bool(yearly)
    params = {"special": {"kind": kind, "lead_days": DEFAULT_LEAD if lead_days is None else max(0, int(lead_days)),
                          "person": person or None, "person_id": person_id or None, "note": note or None,
                          "source": source}}
    start = datetime(first.year, first.month, first.day, 9, 0, tzinfo=_tz())
    key = key or f"{PREFIX}{_slug(person or title)}-{uuid.uuid4().hex[:4]}"
    rule = {"key": key, "type": "event", "title": title[:200], "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(), "recurrence": "FREQ=YEARLY" if yearly else None,
            "params": params, "description": note or KIND_LABEL[kind]}
    if by != "user":                    # a module (Persone…) with a stable key: the owner's edits win
        try:
            current = agenda.get(key)
        except agenda.AgendaError:
            current = None
        if current and (current["user_modified"] or current["status"] == "cancelled"):
            return current
        if current:
            return agenda.update(key, {"title": rule["title"], "start_at": rule["start_at"],
                                       "end_at": rule["end_at"], "params": params}, by=f"module:{by}")
    item = agenda.create(title=rule["title"], type_="event", owner=OWNER, start_at=rule["start_at"],
                         end_at=rule["end_at"], recurrence=rule["recurrence"], description=rule["description"],
                         key=key, params=params, created_by=by)
    logger.info("event=special_added key=%s kind=%s yearly=%s by=%s", key, kind, yearly, by)
    return item


def remove(key: str) -> dict:
    if not str(key).startswith(PREFIX):
        raise agenda.AgendaError("not a special moment", 404)
    return agenda.cancel(key, by="user")


def sync_birthday(birth_date: Any) -> dict | None:
    """``themis.personal.birth_date`` → the owner's birthday (module rule: the owner's own edits of it win)."""
    text = str(birth_date or "").strip()
    if not text:
        return None
    try:
        day = _parse_day(text)
    except agenda.AgendaError:
        logger.warning("event=special_birth_date_invalid value_len=%d", len(text))
        return None
    start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=_tz())
    rule = {"key": BIRTH_KEY, "type": "event", "title": "Il tuo compleanno", "start_at": start.isoformat(),
            "end_at": (start + timedelta(hours=1)).isoformat(), "recurrence": "FREQ=YEARLY",
            "params": {"special": {"kind": "birthday", "lead_days": 0, "source": "impostazioni personali"}}}
    return agenda.register_rules(OWNER, [rule])[0]


# ── proposals (the assistant discovers, the owner confirms through Hermes) ───
def propose(*, title: str, day: str, kind: str = "custom", person: str = "", evidence: str = "",
            lead_days: int | None = None) -> dict:
    _parse_day(day)
    body = {"title": title, "day": str(day)[:10], "kind": kind if kind in KINDS else "custom", "person": person,
            "lead_days": lead_days, "source": "proposta dell'assistente"}
    pid = uuid.uuid4().hex[:8]
    when = _parse_day(day).strftime("%d/%m")
    text = f"Ho trovato una data importante: <b>{title}</b> il {when}."
    if evidence:
        text += f"\n<i>{evidence[:300]}</i>"
    text += "\nLa aggiungo ai tuoi eventi speciali?"
    hermes_client.publish_event("assistant", "service.action_required", f"special.proposal.{pid}", {
        "_title": "Evento speciale da aggiungere?", "_message": text, "_source": "Calendario", "_level": "info",
        "dedupe_key": f"special.proposal:{_slug(title)}:{body['day']}",
        "_actions": [{"id": "add", "label": "Aggiungi", "style": "success", "service": "chronos", "method": "POST",
                      "path": "/api/special", "body": body},
                     {"id": "no", "label": "No", "service": "chronos", "method": "POST",
                      "path": "/api/special/proposal/declined", "body": {"title": title, "day": body["day"]}}]})
    logger.info("event=special_proposed proposal=%s kind=%s", pid, body["kind"])
    return {"proposed": True, "proposal_id": pid}


# ── daily pass ───────────────────────────────────────────────────────────────
def _push_moment(moment: dict) -> int:
    """``special_moment`` to the modules that asked for it (Hub capability ``special_moment_endpoint``)."""
    sent = 0
    try:
        services = (requests.get(f"{_HUB}/registry/services", timeout=5).json() or {}).get("services") or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=special_registry_failed error=%s", exc)
        services = []
    for svc in services if isinstance(services, list) else []:
        path = ((svc.get("capabilities") or {}) if isinstance(svc, dict) else {}).get("special_moment_endpoint")
        if not path:
            continue
        try:
            requests.post(f"{_HUB}/route/{svc['name']}/{str(path).lstrip('/')}",
                          json={"method": "POST", "headers": {}, "query": {}, "body": moment, "timeout_seconds": 10},
                          timeout=12)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[🔄] event=special_push_failed service=%s error=%s", svc.get("name"), exc)
    return sent


def run_daily(today: date | None = None) -> dict:
    today = today or _today()
    lead, now = [], []
    for s in list_special(today):
        if s["in_days"] is None or s["status"] != "confirmed":
            continue
        who = f" di {s['person']}" if s.get("person") else ""
        if s["in_days"] == 0:
            now.append(s)
            hermes_client.publish_event("assistant", "special.today", s["key"], {
                "_title": s["title"], "_message": f"Oggi: <b>{s['title']}</b>{who}.", "_source": "Calendario",
                "_level": "success", "dedupe_key": f"special.today:{s['key']}:{today.isoformat()}",
                "replaces": f"special.{s['key']}", "_link": {"module": "chronos", "page": "eventi"}})
            moment = {"key": s["key"], "title": s["title"], "kind": s["kind"], "person": s.get("person"),
                      "person_id": s.get("person_id"), "date": today.isoformat()}
            _push_moment(moment)
            try:
                from services import routines
                routines.on_signal("special_moment", moment)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[🔄] event=special_routines_failed error=%s", exc)
        elif s["lead_days"] and s["in_days"] == s["lead_days"]:
            lead.append(s)
            hermes_client.publish_event("assistant", "special.soon", s["key"], {
                "_title": f"Tra {s['in_days']} giorni", "_source": "Calendario", "_level": "info",
                "_message": f"Tra {s['in_days']} giorni: <b>{s['title']}</b>{who} ({s['next'][8:10]}/{s['next'][5:7]}).",
                "dedupe_key": f"special.soon:{s['key']}:{s['next']}", "replaces": f"special.{s['key']}", "_link": {"module": "chronos", "page": "eventi"}})
    logger.info("event=special_daily today=%d soon=%d", len(now), len(lead))
    return {"today": [s["key"] for s in now], "soon": [s["key"] for s in lead]}


def today_moments() -> list[dict]:
    """For «what to show now» (Aphrodite) and the recap: the moments of today."""
    return [s for s in list_special() if s["in_days"] == 0]

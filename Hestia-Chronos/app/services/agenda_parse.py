"""Natural-language quick add + ICS feed for the assistant agenda.

``parse(text)``: "domani alle 15 dentista" → draft fields for the WebUI editor
(the user reviews them; nothing is created here). Oracle does the language part
(``/api/llm/generate`` through Hub); Chronos validates dates and RRULE.

``to_ics(occurrences)``: read-only iCalendar export of the agenda (phones).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from dateutil.rrule import rrulestr

logger = logging.getLogger("hestia_chronos.agenda_parse")

_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
_TZ_DEFAULT = os.getenv("CHRONOS_DISPLAY_TZ") or os.getenv("TZ") or "Europe/Rome"
_TYPES = {"event", "task", "job", "window"}
_DAYS_IT = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

# Caveman prompt: paid every call by the local model.
_PROMPT = """Estrai voce agenda. Rispondi SOLO JSON.
Ora: {now} ({weekday}), tz {tz}.
Testo: "{text}"
JSON: {{"title":str,"type":"event|task|job|window","start_at":"YYYY-MM-DDTHH:MM","end_at":"YYYY-MM-DDTHH:MM"|null,"recurrence":"RRULE"|null,"description":str|null}}
Regole: ora locale tz. Niente ora -> 09:00. Durata non detta: event 60 min, altri null.
Ripetizione (ogni giorno/lunedì/settimana) -> RRULE es FREQ=WEEKLY;BYDAY=MO, type job se azione periodica.
Finestra/intervallo permesso -> window con end_at. Titolo breve, senza data/ora."""


class ParseError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _generate(prompt: str, timeout: float = 45) -> str:
    resp = requests.post(
        f"{_HUB}/route/oracle/api/llm/generate",
        json={"method": "POST", "headers": {}, "query": {}, "body": {"prompt": prompt},
              "timeout_seconds": timeout},
        timeout=timeout + 5)
    resp.raise_for_status()
    routed = resp.json() if resp.content else {}
    if int(routed.get("status_code", 500)) >= 400:
        raise ParseError(f"Oracle: {str(routed.get('payload'))[:200]}", 502)
    payload = routed.get("payload") or {}
    return str(payload.get("response") or payload.get("raw") or "") if isinstance(payload, dict) else str(payload)


def _extract_json(raw: str) -> dict:
    raw = re.sub(r"^```[a-zA-Z]*\s*|```\s*$", "", raw.strip())
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ParseError("risposta non in JSON", 502)
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise ParseError(f"JSON non valido: {exc}", 502) from exc
    if not isinstance(data, dict):
        raise ParseError("JSON non è un oggetto", 502)
    return data


def _local(value: object, tz: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def normalize(data: dict, text: str, now: datetime, tz: ZoneInfo) -> dict:
    """Validate the model's draft; anything wrong is dropped (the editor has defaults)."""
    title = str(data.get("title") or "").strip()[:200] or text.strip()[:200]
    kind = str(data.get("type") or "event").strip().lower()
    kind = kind if kind in _TYPES else "event"
    start = _local(data.get("start_at"), tz)
    end = _local(data.get("end_at"), tz)
    if start is None:
        start = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    if end is not None and end <= start:
        end = None
    if kind == "event" and end is None:
        end = start + timedelta(minutes=60)
    rule = str(data.get("recurrence") or "").strip().removeprefix("RRULE:") or None
    if rule:
        try:
            rrulestr(rule, dtstart=start.replace(tzinfo=None))
        except (ValueError, TypeError):
            logger.info("[🔄] event=agenda_parse_bad_rrule rule=%s", rule[:120])
            rule = None
    if kind == "window" and end is None:
        kind = "event"
        end = start + timedelta(minutes=60)
    desc = str(data.get("description") or "").strip()[:1000] or None
    return {"title": title, "type": kind, "start_at": start.isoformat(), "end_at": end.isoformat() if end else None,
            "recurrence": rule, "description": desc}


def parse(text: str, now: datetime | None = None, tz_name: str | None = None) -> dict:
    text = (text or "").strip()
    if len(text) < 3:
        raise ParseError("testo troppo corto")
    try:
        tz = ZoneInfo(tz_name or _TZ_DEFAULT)
    except Exception:
        tz = ZoneInfo(_TZ_DEFAULT)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    prompt = _PROMPT.format(now=now.strftime("%Y-%m-%dT%H:%M"), weekday=_DAYS_IT[now.weekday()], tz=tz.key,
                            text=text[:400].replace('"', "'"))
    try:
        raw = _generate(prompt)
    except ParseError:
        raise
    except Exception as exc:
        logger.warning("[🔄] event=agenda_parse_oracle_failed error=%s", exc)
        raise ParseError("Oracle non raggiungibile", 503) from exc
    draft = normalize(_extract_json(raw), text, now, tz)
    logger.info("event=agenda_parsed type=%s recurring=%s", draft["type"], bool(draft["recurrence"]))
    return draft


# ── ICS ─────────────────────────────────────────────────────────────────────

def _esc(v: str) -> str:
    return str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    out, b = [], line.encode("utf-8")
    while len(b) > 74:
        cut = 74
        while cut and (b[cut] & 0xC0) == 0x80:   # don't split a UTF-8 sequence
            cut -= 1
        out.append(b[:cut].decode("utf-8"))
        b = b" " + b[cut:]
    out.append(b.decode("utf-8"))
    return out


def _utc(iso: str) -> str:
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def to_ics(occurrences: list[dict], name: str = "Agenda di Hestia") -> str:
    """Expanded occurrences (not RRULEs: overrides/skips are already applied) as VEVENTs."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Hestia//Agenda//IT", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H"]
    for o in occurrences:
        if o.get("skipped"):
            continue
        start = o.get("start")
        if not start:
            continue
        end = o.get("end") or (datetime.fromisoformat(str(start).replace("Z", "+00:00")) + timedelta(minutes=15)).isoformat()
        uid = f"{o.get('key')}-{_utc(o.get('occurrence') or start)}@hestia"
        desc = " · ".join(x for x in (o.get("owner"), o.get("type"), o.get("description")) if x)
        lines += ["BEGIN:VEVENT", f"UID:{_esc(uid)}", f"DTSTAMP:{stamp}", f"DTSTART:{_utc(start)}",
                  f"DTEND:{_utc(end)}", f"SUMMARY:{_esc(o.get('title') or '')}"]
        if desc:
            lines.append(f"DESCRIPTION:{_esc(desc)}")
        if o.get("status") in {"cancelled"}:
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(f for line in lines for f in _fold(line)) + "\r\n"

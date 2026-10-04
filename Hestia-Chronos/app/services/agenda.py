"""Assistant agenda — Hestia's own calendar (source ``hestia``).

Separate from the user's calendars (never synced to Google/Outlook, never
nagged as user reminders), but readable by the user and by every module.

Item types
----------
- ``event``  informational / planned (e.g. "Forge: sviluppo X stanotte").
- ``task``   one-off action to execute at ``start_at`` (repairs, follow-ups).
- ``job``    recurring action (RRULE), e.g. "Scout: controlla email ogni 30 min".
- ``window`` period in which something is allowed (RRULE + duration), e.g.
             "Claude Pro: notti prima del reset". Modules ask
             ``window_status(key)`` instead of hardcoding times.

Rules are data: modules *register* defaults (idempotent by ``key``); the user
can move, change, cancel, skip a single occurrence (dismiss) or run now. A rule
edited by the user (``user_modified``) is never overwritten by its module.

Actions ``{service, method, path, body}`` are executed through Hub at the due
time by the agenda worker (one-offs retried up to ``max_attempts``).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dateutil.rrule import rrulestr

from core import archive_client

logger = logging.getLogger("hestia_chronos.agenda")

SOURCE = "hestia"
TYPES = ("event", "task", "job", "window")
_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
_TZ_DEFAULT = os.getenv("CHRONOS_DISPLAY_TZ") or os.getenv("TZ") or "Europe/Rome"
_TICK = max(15, int(os.getenv("CHRONOS_AGENDA_TICK_SECONDS", "60")))
_MAX_ATTEMPTS = int(os.getenv("CHRONOS_AGENDA_MAX_ATTEMPTS", "5"))
_lock = threading.RLock()


class AgendaError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ── persistence (Archive calendar_items, source=hestia) ────────────────────


def _raw_items() -> list[dict]:
    rows = archive_client._route_archive(
        "GET", "api/calendar/items", query={"source": SOURCE, "limit": 1000}, timeout=10)
    return rows if isinstance(rows, list) else []


def _to_item(row: dict) -> dict:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    return {
        "id": row.get("id"),
        "key": row.get("external_id"),
        "type": meta.get("type") or row.get("kind") or "event",
        "owner": meta.get("owner") or "user",
        "title": row.get("title"),
        "description": row.get("description"),
        "start_at": row.get("start_at"),
        "end_at": row.get("end_at"),
        "recurrence": row.get("recurrence"),
        "tz": meta.get("tz") or _TZ_DEFAULT,
        "status": row.get("status") or "confirmed",
        "action": meta.get("action"),
        "params": meta.get("params") or {},
        "skips": meta.get("skips") or [],
        "overrides": meta.get("overrides") or {},
        "user_modified": bool(meta.get("user_modified")),
        "created_by": meta.get("created_by") or "user",
        "last_fired": meta.get("last_fired"),
        "last_result": meta.get("last_result"),
        "runs": meta.get("runs") or [],
        "attempts": int(meta.get("attempts") or 0),
    }


def _save(item: dict) -> dict:
    meta_keys = ("type", "owner", "tz", "action", "params", "skips", "overrides", "user_modified",
                 "created_by", "last_fired", "last_result", "runs", "attempts")
    payload = {
        "external_id": item["key"],
        "source": SOURCE,
        "kind": item["type"],
        "title": item["title"],
        "description": item.get("description"),
        "start_at": item["start_at"],
        "end_at": item.get("end_at"),
        "recurrence": item.get("recurrence"),
        "status": item.get("status") or "confirmed",
        "nag_enabled": False,     # never a user reminder
        "meta": {k: item.get(k) for k in meta_keys},
    }
    saved = archive_client._route_archive("POST", "api/calendar/items", body=payload, timeout=10)
    if not isinstance(saved, dict):
        raise AgendaError("Archive unavailable: agenda item not saved", 503)
    return _to_item(saved)


def list_items(owner: str | None = None, type_: str | None = None,
               include_cancelled: bool = False) -> list[dict]:
    items = [_to_item(r) for r in _raw_items()]
    if not include_cancelled:
        items = [i for i in items if i["status"] not in {"cancelled", "completed"}]
    if owner:
        items = [i for i in items if i["owner"] == owner]
    if type_:
        items = [i for i in items if i["type"] == type_]
    return items


def get(ref: str | int) -> dict:
    ref = str(ref).strip()
    for item in (_to_item(r) for r in _raw_items()):
        if str(item["id"]) == ref or item["key"] == ref:
            return item
    raise AgendaError(f"agenda item '{ref}' not found", 404)


# ── time helpers ────────────────────────────────────────────────────────────


def _parse(dt: Any, tz: str) -> datetime:
    if isinstance(dt, datetime):
        value = dt
    else:
        value = datetime.fromisoformat(str(dt).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo(tz))
    return value


def _norm_rrule(rule: str | None) -> str | None:
    if not rule:
        return None
    rule = str(rule).strip()
    return rule if rule.upper().startswith("RRULE:") else f"RRULE:{rule}"


def occurrences(item: dict, start: datetime, end: datetime) -> list[dict]:
    """Expand an item into occurrences overlapping [start, end).

    Recurrence is evaluated in local wall time (``tz``) so "every day 00:00"
    stays at midnight across DST changes.
    """
    tz = ZoneInfo(item.get("tz") or _TZ_DEFAULT)
    first = _parse(item["start_at"], item.get("tz") or _TZ_DEFAULT).astimezone(tz)
    last_end = _parse(item["end_at"], item.get("tz") or _TZ_DEFAULT).astimezone(tz) if item.get("end_at") else None
    duration = (last_end - first) if last_end else timedelta(0)
    skips = set(item.get("skips") or [])
    overrides = item.get("overrides") or {}
    runs = {r.get("occurrence"): r for r in (item.get("runs") or []) if isinstance(r, dict)}
    out: list[dict] = []
    # Moved occurrences ("only this one") may come from outside [start, end): widen the base scan.
    pad = timedelta(days=8) if overrides else timedelta(0)
    if not item.get("recurrence"):
        starts = [first]
    else:
        rule = rrulestr(_norm_rrule(item["recurrence"]), dtstart=first.replace(tzinfo=None))
        lo = (start.astimezone(tz) - duration - pad).replace(tzinfo=None)
        hi = (end.astimezone(tz) + pad).replace(tzinfo=None)
        starts = [s.replace(tzinfo=tz) for s in rule.between(lo, hi, inc=True)]
    for s in starts:
        key = s.astimezone(timezone.utc).isoformat()
        e = s + duration
        moved = overrides.get(key)
        if moved:
            s = _parse(moved["start"], item.get("tz") or _TZ_DEFAULT).astimezone(tz)
            e = _parse(moved["end"], item.get("tz") or _TZ_DEFAULT).astimezone(tz) if moved.get("end") else s + duration
        has_len = e > s
        if e < start or s >= end:
            if not (not has_len and start <= s < end):
                continue
        if has_len and e == start:
            continue
        out.append({"item_id": item["id"], "key": item["key"], "type": item["type"],
                    "owner": item["owner"], "title": item["title"],
                    "start": s.isoformat(), "end": e.isoformat() if has_len else None,
                    "occurrence": key, "skipped": key in skips, "moved": bool(moved),
                    "status": item.get("status"), "recurring": bool(item.get("recurrence")),
                    "created_by": item.get("created_by") or "user",
                    "run": _run_view(runs.get(key))})
    return out


_RUNS_KEEP = 50


def _run_view(run: dict | None) -> dict | None:
    if not run:
        return None
    return {"ok": bool(run.get("ok")), "detail": run.get("detail"), "at": run.get("at"),
            "duration_ms": run.get("duration_ms")}


def _record_run(item: dict, occurrence: str | None, ok: bool, detail: str, at: str, by: str,
                duration_ms: int | None = None) -> None:
    """Per-occurrence run log (capped): the calendar shows ok/failed per occurrence."""
    run = {"occurrence": occurrence or f"manual:{at}", "ok": ok, "detail": detail, "at": at, "by": by,
           "duration_ms": duration_ms}
    item["runs"] = ([r for r in (item.get("runs") or []) if isinstance(r, dict)] + [run])[-_RUNS_KEEP:]


def agenda(start: datetime, end: datetime, owner: str | None = None, type_: str | None = None,
           include_done: bool = False) -> list[dict]:
    """Occurrences in [start, end). ``include_done``: also completed/cancelled items (calendar history)."""
    rows: list[dict] = []
    for item in list_items(owner=owner, type_=type_, include_cancelled=include_done):
        try:
            rows.extend(occurrences(item, start, end))
        except Exception as exc:
            logger.warning("[🔄] event=agenda_expand_failed item=%s error=%s", item.get("id"), exc)
    return sorted(rows, key=lambda r: r["start"])


def window_status(key: str, now: datetime | None = None) -> dict:
    """Is window ``key`` open now? Unknown/cancelled key → closed (caller decides fallback)."""
    now = now or datetime.now(timezone.utc)
    try:
        item = get(key)
    except AgendaError:
        return {"key": key, "exists": False, "active": False}
    if item["type"] != "window" or item["status"] in {"cancelled", "completed", "paused"}:
        return {"key": key, "exists": True, "active": False, "status": item["status"]}
    current = [o for o in occurrences(item, now - timedelta(days=8), now + timedelta(seconds=1))
               if o["end"] and _parse(o["start"], "UTC") <= now < _parse(o["end"], "UTC")]
    open_now = [o for o in current if not o["skipped"]]
    upcoming = [o for o in occurrences(item, now, now + timedelta(days=60)) if not o["skipped"]
                and _parse(o["start"], "UTC") > now]
    return {
        "key": key, "exists": True, "active": bool(open_now),
        "until": open_now[0]["end"] if open_now else None,
        "skipped_now": bool(current) and not open_now,
        "next_open": upcoming[0]["start"] if upcoming else None,
        "params": item["params"],
    }


# ── mutations ───────────────────────────────────────────────────────────────


def create(*, title: str, type_: str = "event", owner: str = "user", start_at: str,
           end_at: str | None = None, recurrence: str | None = None, description: str | None = None,
           action: dict | None = None, key: str | None = None, params: dict | None = None,
           tz: str | None = None, created_by: str = "user") -> dict:
    if type_ not in TYPES:
        raise AgendaError(f"type must be one of {TYPES}")
    if type_ == "window" and not end_at:
        raise AgendaError("a window needs end_at (duration of each occurrence)")
    if type_ in {"task", "job"} and action and not (action.get("service") and action.get("path")):
        raise AgendaError("action needs service and path")
    tz = tz or _TZ_DEFAULT
    item = {
        "key": key or f"{owner}:{uuid.uuid4().hex[:10]}",
        "type": type_, "owner": owner, "title": title, "description": description,
        "start_at": _parse(start_at, tz).isoformat(),
        "end_at": _parse(end_at, tz).isoformat() if end_at else None,
        "recurrence": _norm_rrule(recurrence), "tz": tz, "status": "confirmed",
        "action": action, "params": params or {}, "skips": [], "user_modified": False,
        "created_by": created_by, "last_fired": None, "last_result": None, "attempts": 0,
    }
    if recurrence:
        rrulestr(item["recurrence"], dtstart=datetime(2026, 1, 1))  # validate early
    with _lock:
        return _save(item)


def register_rules(owner: str, rules: list[dict]) -> list[dict]:
    """Module defaults, idempotent by key. User-edited rules are left untouched."""
    existing = {i["key"]: i for i in list_items(include_cancelled=True)}
    saved: list[dict] = []
    for rule in rules:
        key = str(rule.get("key") or "").strip()
        if not key:
            raise AgendaError("each rule needs a stable key")
        current = existing.get(key)
        if current and (current["user_modified"] or current["status"] == "cancelled"):
            saved.append(current)          # user decision wins
            continue
        if current:
            changed = {f: rule[f] for f in ("title", "description", "start_at", "end_at", "recurrence",
                                            "action", "params") if f in rule}
            item = dict(current)
            item.update(changed)
            if "start_at" in changed:
                item["start_at"] = _parse(changed["start_at"], item["tz"]).isoformat()
            if changed.get("end_at"):
                item["end_at"] = _parse(changed["end_at"], item["tz"]).isoformat()
            item["recurrence"] = _norm_rrule(item.get("recurrence"))
            with _lock:
                saved.append(_save(item))
        else:
            saved.append(create(title=rule.get("title") or key, type_=rule.get("type", "job"), owner=owner,
                                start_at=rule["start_at"], end_at=rule.get("end_at"),
                                recurrence=rule.get("recurrence"), description=rule.get("description"),
                                action=rule.get("action"), key=key, params=rule.get("params"),
                                tz=rule.get("tz"), created_by=owner))
    logger.info("event=agenda_rules_registered owner=%s count=%d", owner, len(saved))
    return saved


def update(ref: str | int, changes: dict, by: str = "user") -> dict:
    with _lock:
        item = get(ref)
        for field in ("title", "description", "recurrence", "action", "params", "status", "tz"):
            if field in changes and changes[field] is not None:
                item[field] = changes[field]
        if changes.get("start_at"):
            new_start = _parse(changes["start_at"], item["tz"])
            if item.get("end_at") and not changes.get("end_at"):
                # moving keeps the duration
                old_start = _parse(item["start_at"], item["tz"])
                item["end_at"] = (_parse(item["end_at"], item["tz"]) + (new_start - old_start)).isoformat()
            item["start_at"] = new_start.isoformat()
            item["attempts"] = 0
        if changes.get("end_at"):
            item["end_at"] = _parse(changes["end_at"], item["tz"]).isoformat()
        item["recurrence"] = _norm_rrule(item.get("recurrence"))
        if by == "user":
            item["user_modified"] = True
        return _save(item)


def cancel(ref: str | int, by: str = "user") -> dict:
    return update(ref, {"status": "cancelled"}, by=by)


def skip(ref: str | int, occurrence: str | None = None, by: str = "user") -> dict:
    """Dismiss one occurrence (default: the current or next one)."""
    with _lock:
        item = get(ref)
        now = datetime.now(timezone.utc)
        if occurrence:
            occ = _parse(occurrence, item["tz"]).astimezone(timezone.utc).isoformat()
        else:
            candidates = [o for o in occurrences(item, now - timedelta(days=1), now + timedelta(days=400))
                          if not o["skipped"] and (
                              (o["end"] and _parse(o["end"], "UTC") > now) or _parse(o["start"], "UTC") >= now)]
            if not candidates:
                raise AgendaError("no upcoming occurrence to skip")
            occ = candidates[0]["occurrence"]
        if occ not in item["skips"]:
            item["skips"] = sorted(item["skips"] + [occ])[-200:]
        if not item.get("recurrence"):
            item["status"] = "cancelled"     # skipping a one-off = dismiss it
        if by == "user":
            item["user_modified"] = True
        return _save(item)


def unskip(ref: str | int, occurrence: str, by: str = "user") -> dict:
    with _lock:
        item = get(ref)
        occ = _parse(occurrence, item["tz"]).astimezone(timezone.utc).isoformat()
        item["skips"] = [s for s in item["skips"] if s != occ]
        if by == "user":
            item["user_modified"] = True
        return _save(item)


def move_occurrence(ref: str | int, occurrence: str, start_at: str | None = None,
                    end_at: str | None = None, reset: bool = False, by: str = "user") -> dict:
    """Move ONE occurrence (exception, like Google Calendar "only this event").

    Keeps the item key, so modules asking ``window_status(key)`` or jobs fired by
    the worker follow the moved time. ``reset`` restores the original time.
    """
    with _lock:
        item = get(ref)
        occ = _parse(occurrence, item["tz"]).astimezone(timezone.utc).isoformat()
        overrides = dict(item.get("overrides") or {})
        if reset:
            overrides.pop(occ, None)
        else:
            if not start_at:
                raise AgendaError("start_at required")
            new_start = _parse(start_at, item["tz"])
            new_end = _parse(end_at, item["tz"]) if end_at else None
            if new_end and new_end <= new_start:
                raise AgendaError("end_at must be after start_at")
            overrides[occ] = {"start": new_start.isoformat(), "end": new_end.isoformat() if new_end else None}
        item["overrides"] = dict(sorted(overrides.items())[-200:])
        if not item.get("recurrence") and not reset:
            # one-off: just move the item itself
            item.pop("overrides", None)
            item["overrides"] = {}
            duration = (_parse(item["end_at"], item["tz"]) - _parse(item["start_at"], item["tz"])) if item.get("end_at") else None
            item["start_at"] = _parse(start_at, item["tz"]).isoformat()
            if end_at:
                item["end_at"] = _parse(end_at, item["tz"]).isoformat()
            elif duration is not None:
                item["end_at"] = (_parse(start_at, item["tz"]) + duration).isoformat()
            item["attempts"] = 0
            item["last_fired"] = None if item["type"] == "task" else item.get("last_fired")
        if by == "user":
            item["user_modified"] = True
        return _save(item)


# ── execution ───────────────────────────────────────────────────────────────


def _fire(action: dict) -> tuple[bool, str]:
    try:
        resp = requests.post(
            f"{_HUB}/route/{action['service']}/{str(action['path']).lstrip('/')}",
            json={"method": str(action.get("method") or "POST").upper(), "headers": {},
                  "query": action.get("query") or {}, "body": action.get("body"),
                  "timeout_seconds": float(action.get("timeout_seconds") or 30)},
            timeout=float(action.get("timeout_seconds") or 30) + 5)
        routed = resp.json() if resp.ok and resp.content else {}
        status = int(routed.get("status_code", resp.status_code if not resp.ok else 500))
        return status < 400, f"{status}: {str(routed.get('payload'))[:200]}"
    except Exception as exc:
        return False, str(exc)[:200]


def run_now(ref: str | int, by: str = "user") -> dict:
    item = get(ref)
    if not item.get("action"):
        raise AgendaError("item has no action to run")
    t0 = time.perf_counter()
    ok, detail = _fire(item["action"])
    ms = int((time.perf_counter() - t0) * 1000)
    with _lock:
        item = get(ref)
        at = datetime.now(timezone.utc).isoformat()
        item["last_result"] = {"ok": ok, "detail": detail, "at": at, "by": by}
        _record_run(item, None, ok, detail, at, by, ms)
        _save(item)
    return {"ok": ok, "detail": detail}


def tick(now: datetime | None = None) -> dict:
    """Execute due actions. Recurring jobs fire their latest due occurrence once
    (no storm after downtime); one-off tasks retry up to max_attempts."""
    now = now or datetime.now(timezone.utc)
    fired = failed = 0
    for item in list_items():
        if item["type"] not in {"task", "job"} or not item.get("action") or item["status"] in {"paused", "failed"}:
            continue
        try:
            since = _parse(item["last_fired"], "UTC") if item.get("last_fired") else now - timedelta(seconds=_TICK * 2)
            due = [o for o in occurrences(item, since, now + timedelta(seconds=1))
                   if not o["skipped"] and since < _parse(o["start"], "UTC") <= now]
            if not item.get("recurrence"):
                start = _parse(item["start_at"], item["tz"])
                due = [] if start > now or item["last_fired"] else [{"occurrence": start.astimezone(timezone.utc).isoformat()}]
            if not due:
                continue
            t0 = time.perf_counter()
            ok, detail = _fire(item["action"])
            ms = int((time.perf_counter() - t0) * 1000)
            with _lock:
                fresh = get(item["id"])
                fresh["last_result"] = {"ok": ok, "detail": detail, "at": now.isoformat()}
                _record_run(fresh, str(due[-1].get("occurrence") or ""), ok, detail, now.isoformat(), "agenda", ms)
                if ok or fresh.get("recurrence"):
                    fresh["last_fired"] = now.isoformat()
                    fresh["attempts"] = 0
                    if ok and not fresh.get("recurrence"):
                        fresh["status"] = "completed"
                else:
                    fresh["attempts"] = int(fresh.get("attempts") or 0) + 1
                    if fresh["attempts"] >= _MAX_ATTEMPTS:
                        fresh["status"] = "failed"
                _save(fresh)
            fired += int(ok)
            failed += int(not ok)
            if not ok:
                logger.warning("[🔄] event=agenda_action_failed item=%s detail=%s", item["key"], detail)
        except Exception as exc:
            logger.warning("[🔄] event=agenda_tick_item_error item=%s error=%s", item.get("key"), exc)
    if fired or failed:
        logger.info("event=agenda_tick fired=%d failed=%d", fired, failed)
    return {"fired": fired, "failed": failed}


def start_worker() -> None:
    def _loop():
        while True:
            time.sleep(_TICK)
            try:
                tick()
            except Exception as exc:
                logger.warning("[🔄] event=agenda_worker_error error=%s", exc)

    threading.Thread(target=_loop, daemon=True, name="agenda-worker").start()
    logger.info("event=agenda_worker_started tick=%ds", _TICK)


# ── Templates: what the user can create per module (WebUI wizard) ─────────────
# In memory: modules re-assert them with their rules (hourly + at startup), so a restart heals itself.
_TEMPLATES: dict[str, dict[str, dict]] = {}


def register_templates(owner: str, templates: list[dict]) -> int:
    clean: dict[str, dict] = {}
    for t in templates or []:
        if isinstance(t, dict) and t.get("id") and isinstance(t.get("action"), dict):
            clean[str(t["id"])] = {**t, "owner": owner}
    with _lock:
        _TEMPLATES[owner] = clean
    return len(clean)


def list_templates() -> list[dict]:
    with _lock:
        return [t for owner in sorted(_TEMPLATES) for t in _TEMPLATES[owner].values()]


def create_from_template(owner: str, template_id: str, *, values: dict, start_at: str,
                         end_at: str | None = None, recurrence: str | None = None,
                         type_: str | None = None, description: str | None = None) -> dict:
    """User creates an item from a module template: created_by=user (manual → always visible), owner=module."""
    with _lock:
        tpl = (_TEMPLATES.get(owner) or {}).get(template_id)
    if not tpl:
        raise AgendaError(f"template {owner}/{template_id} not found (module offline?)", 404)
    values = {k: v for k, v in (values or {}).items() if k in (tpl.get("fields") or {})}
    for name in tpl.get("required") or []:
        if values.get(name) in (None, ""):
            raise AgendaError(f"field '{name}' required")
    fields = tpl.get("fields") or {}
    for name, spec in fields.items():
        if name not in values and isinstance(spec, dict) and "default" in spec:
            values[name] = spec["default"]
        if isinstance(spec, dict) and spec.get("enum") and name in values and values[name] not in spec["enum"]:
            raise AgendaError(f"field '{name}' must be one of {spec['enum']}")
    kind = type_ if type_ in (tpl.get("types") or [tpl.get("type")]) else tpl.get("type", "task")
    action = dict(tpl["action"])
    path = str(action.get("path") or "")
    body = dict(action.get("body") or {})
    from urllib.parse import quote
    for name, v in values.items():
        if (fields.get(name) or {}).get("in") == "path":
            path = path.replace("{" + name + "}", quote(str(v), safe=""))
        else:
            body[name] = v
    action.update(path=path, body=body)
    try:
        title = str(tpl.get("title") or tpl.get("label")).format(**{k: v for k, v in values.items()})
    except (KeyError, IndexError, ValueError):
        title = str(tpl.get("label"))
    if kind == "window" and not end_at and tpl.get("duration_minutes"):
        end_at = (_parse(start_at, _TZ_DEFAULT) + timedelta(minutes=int(tpl["duration_minutes"]))).isoformat()
    return create(title=title[:200], type_=kind, owner=owner, start_at=start_at, end_at=end_at,
                  recurrence=(recurrence or None) if kind in ("job", "window", "event") else None,
                  description=description or tpl.get("description"),
                  action=action if kind in ("task", "job") else None,
                  key=f"{owner}.tpl.{template_id}.{uuid.uuid4().hex[:6]}",
                  params={"template": template_id, "values": values}, created_by="user")

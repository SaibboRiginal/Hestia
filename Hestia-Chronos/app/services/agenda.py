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

Links: an item may name a ``parent`` (key). Cancelling the parent cancels its
live children (``by=cascade:<key>``); a child that fails, or that the user
cancels, marks the parent (``last_result`` + run log; a one-off parent fails
too). Generic — Forge links its task mirror to the request that started it.
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
from core import chronos_settings as CS

logger = logging.getLogger("hestia_chronos.agenda")

SOURCE = "hestia"
TYPES = ("event", "task", "job", "window")
_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
_TZ_DEFAULT = os.getenv("TZ") or "Europe/Rome"     # infrastructure: container timezone


def _tick_seconds() -> int:
    """``chronos.agenda.tick_seconds`` (live, re-read every loop iteration)."""
    try:
        return max(15, int(CS.settings.get(CS.AGENDA_TICK)))
    except (TypeError, ValueError):
        return 60


def _max_attempts() -> int:
    try:
        return max(1, int(CS.settings.get(CS.AGENDA_MAX_ATTEMPTS)))
    except (TypeError, ValueError):
        return 5
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
        "parent": meta.get("parent") or None,
    }


def _save(item: dict) -> dict:
    meta_keys = ("type", "owner", "tz", "action", "params", "skips", "overrides", "user_modified",
                 "created_by", "last_fired", "last_result", "runs", "attempts", "parent")
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
    out = {"ok": bool(run.get("ok")), "detail": run.get("detail"), "at": run.get("at"),
           "duration_ms": run.get("duration_ms")}
    if run.get("flex"):
        out["flex"] = run["flex"]
    return out


def _record_run(item: dict, occurrence: str | None, ok: bool, detail: str, at: str, by: str,
                duration_ms: int | None = None, flex: dict | None = None) -> None:
    """Per-occurrence run log (capped): the calendar shows ok/failed per occurrence.
    ``flex``: ``{from, reason}`` when a flexible job fired away from its nominal time."""
    run = {"occurrence": occurrence or f"manual:{at}", "ok": ok, "detail": detail, "at": at, "by": by,
           "duration_ms": duration_ms}
    if flex:
        run["flex"] = flex
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
           tz: str | None = None, created_by: str = "user", parent: str | None = None) -> dict:
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
        "parent": (parent or "").strip() or None,
    }
    if recurrence:
        rrulestr(item["recurrence"], dtstart=datetime(2026, 1, 1))  # validate early
    with _lock:
        return _save(item)


# Latest declaration of every module's default rules (in memory, re-asserted hourly by ``register_async``):
# what «Ripristina» brings a deleted or changed standard activity back to (§3.9 recap dossier).
_DECLARED: dict[str, dict[str, dict]] = {}


def register_rules(owner: str, rules: list[dict]) -> list[dict]:
    """Module defaults, idempotent by key. User-edited rules are left untouched."""
    existing = {i["key"]: i for i in list_items(include_cancelled=True)}
    saved: list[dict] = []
    with _lock:
        _DECLARED.setdefault(owner, {}).update(
            {str(r.get("key")).strip(): dict(r) for r in rules if str(r.get("key") or "").strip()})
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


def _standard_state(item: dict) -> str:
    if item["status"] == "cancelled":
        return "eliminata"
    if item["status"] == "paused":
        return "in pausa"
    if item["status"] == "failed":
        return "fallita"
    if item["user_modified"]:
        return "modificata"
    return "attiva"


def standard(owner: str | None = None) -> dict:
    """Standard activities: every default rule a module declared (deleted, paused and changed ones included) and
    every template, so the user brings any of them back in one click instead of rebuilding it (§3.9)."""
    rows = []
    for item in list_items(owner=owner, include_cancelled=True):
        if item["created_by"] in {"user", ""} or item["created_by"] != item["owner"] \
                or (item.get("params") or {}).get("retired_by_module") or item["status"] == "completed":
            continue
        state = _standard_state(item)
        rows.append({"key": item["key"], "owner": item["owner"], "type": item["type"], "title": item["title"],
                     "description": item.get("description") or "", "start_at": item["start_at"],
                     "end_at": item.get("end_at"), "recurrence": item.get("recurrence"),
                     "flex": (item.get("params") or {}).get("flex"), "state": state,
                     "can_restore": state != "attiva"})
    order = {"eliminata": 0, "fallita": 1, "in pausa": 2, "modificata": 3, "attiva": 4}
    rows.sort(key=lambda r: (order[r["state"]], r["owner"], r["title"] or ""))
    templates = [t for t in list_templates() if not owner or t.get("owner") == owner]
    return {"activities": rows, "templates": templates,
            "counts": {k: sum(1 for r in rows if r["state"] == k) for k in order}}


def restore(key: str, by: str = "user") -> dict:
    """A standard activity back to its module's declaration: active and no longer user-modified (past skips and
    moved occurrences stay: they are history)."""
    with _lock:
        item = get(key)
        if item["created_by"] != item["owner"] or item["created_by"] in {"user", ""}:
            raise AgendaError("solo le attività standard di un modulo si ripristinano", 400)
        declared = (_DECLARED.get(item["owner"]) or {}).get(item["key"]) or {}
        for f in ("title", "description", "start_at", "end_at", "recurrence", "action", "params"):
            if f in declared:
                item[f] = declared[f]
        if declared.get("start_at"):
            item["start_at"] = _parse(declared["start_at"], item["tz"]).isoformat()
        if declared.get("end_at"):
            item["end_at"] = _parse(declared["end_at"], item["tz"]).isoformat()
        item["recurrence"] = _norm_rrule(item.get("recurrence"))
        item.update(status="confirmed", user_modified=False, attempts=0)
        saved = _save(item)
    logger.info("event=agenda_standard_restored key=%s owner=%s by=%s declared=%s", key, saved["owner"], by,
                bool(declared))
    return saved


def retire_rules(owner: str, keys: list[str]) -> list[str]:
    """A module no longer needs some of its own default rules (e.g. Scout's mail poll replaced by push).
    Only rules the module itself created are cancelled (``params.retired_by_module``); user items stay."""
    wanted = {str(k).strip() for k in keys if str(k).strip()}
    retired: list[str] = []
    for item in list_items(include_cancelled=True):
        if item["key"] not in wanted or item["owner"] != owner or item["created_by"] != owner:
            continue
        if item["status"] == "cancelled":
            continue
        with _lock:
            item = dict(item)
            item["params"] = {**(item.get("params") or {}), "retired_by_module": True}
            _save(item)
        cancel(item["key"], by=f"module:{owner}")
        retired.append(item["key"])
    if retired:
        logger.info("event=agenda_rules_retired owner=%s keys=%s", owner, ",".join(retired))
    return retired


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


_TERMINAL = {"cancelled", "completed", "failed"}


def children(key: str) -> list[dict]:
    return [i for i in (_to_item(r) for r in _raw_items()) if i.get("parent") == key]


def cancel(ref: str | int, by: str = "user") -> dict:
    """Cancel an item; cascade to live children; a user cancel of a child marks its parent."""
    with _lock:
        item = update(ref, {"status": "cancelled"}, by=by)
        for child in children(item["key"]):
            if child["status"] not in _TERMINAL:
                try:
                    cancel(child["key"], by=f"cascade:{item['key']}")
                except AgendaError as exc:
                    logger.warning("[🔄] event=agenda_cascade_cancel_failed item=%s child=%s error=%s",
                                   item["key"], child["key"], exc)
        if item.get("parent") and not by.startswith("cascade:"):
            _mark_parent(item, ok=False, detail=f"voce collegata annullata: {item['title']}", by=by)
        if by.startswith("cascade:"):
            logger.info("event=agenda_cascade_cancelled item=%s by=%s", item["key"], by)
        return item


def link(ref: str | int, parent: str | None, by: str = "user") -> dict:
    """Set (or clear with empty) the parent of an item. No cycles."""
    with _lock:
        item = get(ref)
        parent = (parent or "").strip() or None
        if parent:
            seen, cur = {item["key"]}, parent
            while cur:
                if cur in seen:
                    raise AgendaError("link would create a cycle")
                seen.add(cur)
                cur = get(cur).get("parent")       # 404 if the parent does not exist
        item["parent"] = parent
        logger.info("event=agenda_linked item=%s parent=%s by=%s", item["key"], parent, by)
        return _save(item)


def fail(ref: str | int, detail: str = "", by: str = "module") -> dict:
    """A module reports that the work behind an item failed (e.g. a Forge task). Propagates to the parent."""
    with _lock:
        item = get(ref)
        at = datetime.now(timezone.utc).isoformat()
        item["status"] = "failed"
        item["last_result"] = {"ok": False, "detail": (detail or "fallito")[:300], "at": at, "by": by}
        _record_run(item, None, False, (detail or "fallito")[:300], at, by)
        item = _save(item)
        if item.get("parent"):
            _mark_parent(item, ok=False, detail=f"voce collegata fallita: {item['title']}", by=by)
        return item


def _mark_parent(child: dict, *, ok: bool, detail: str, by: str) -> None:
    """Error/cancel of a child → visible on the parent (one-off parent fails; recurring keeps going)."""
    try:
        parent = get(child["parent"])
    except AgendaError:
        logger.info("[🔄] event=agenda_parent_missing item=%s parent=%s", child["key"], child.get("parent"))
        return
    if parent["status"] in _TERMINAL:
        return
    at = datetime.now(timezone.utc).isoformat()
    parent["last_result"] = {"ok": ok, "detail": detail[:300], "at": at, "by": by}
    _record_run(parent, None, ok, detail[:300], at, f"link:{child['key']}")
    if not ok and not parent.get("recurrence") and parent["type"] in {"task", "event"}:
        parent["status"] = "failed"
    _save(parent)
    logger.info("event=agenda_parent_marked parent=%s child=%s ok=%s", parent["key"], child["key"], ok)
    if parent["status"] == "failed" and parent.get("parent"):
        _mark_parent(parent, ok=False, detail=f"voce collegata fallita: {parent['title']}", by=by)


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
        reactivated = False
        if ok and item["status"] == "failed":
            # A manual run that works fixes what stopped the rule: recurring rules go back on, one-offs are done.
            # Paused stays paused (a user decision).
            item["status"] = "confirmed" if item.get("recurrence") else "completed"
            item["attempts"] = 0
            reactivated = True
            logger.info("event=agenda_reactivated item=%s status=%s by=%s", item["key"], item["status"], by)
        _save(item)
    return {"ok": ok, "detail": detail, "reactivated": reactivated}


def _flex_gap() -> timedelta:
    try:
        return timedelta(minutes=max(0, int(CS.settings.get(CS.FLEX_GAP))))
    except (TypeError, ValueError):
        return timedelta(minutes=15)


def _flex_due(item: dict, since: datetime, now: datetime) -> tuple[list[dict], dict | None]:
    """Due occurrences of a flexible job (``params.flex``): each fires at the time ``flex.plan`` picks around the
    user's events (§3.8 recap dossier). An occurrence the user moved keeps its time. Latest due one only."""
    from services import day_view, flex as F
    rule = (item.get("params") or {}).get("flex")
    tz = ZoneInfo(item.get("tz") or _TZ_DEFAULT)
    gap = _flex_gap()
    ran = {r.get("occurrence") for r in item.get("runs") or [] if isinstance(r, dict)}
    picked: tuple[dict, dict | None] | None = None
    for o in occurrences(item, now - timedelta(days=1), now + timedelta(days=1)):
        if o["skipped"] or o["occurrence"] in ran:
            continue
        nominal = _parse(o["start"], item.get("tz") or _TZ_DEFAULT).astimezone(tz)
        fire, reason = nominal, ""
        rng = None if o["moved"] else F.flex_range(nominal, rule)
        if rng and rng[0] <= now and rng[1] > since:
            try:
                busy = day_view.busy(rng[0] - gap - timedelta(hours=6), rng[1] + gap)
            except Exception as exc:
                logger.warning("[🔄] event=agenda_flex_calendar_failed item=%s error=%s fallback=nominal",
                               item["key"], exc)
                busy = []
            fire, reason = F.plan(nominal, rule, busy, gap)
        if since < fire <= now:
            info = {"from": nominal.isoformat(), "at": fire.isoformat(), "reason": reason} if reason else None
            picked = (o, info)
    if not picked:
        return [], None
    if picked[1]:
        logger.info("event=agenda_flex_moved item=%s from=%s at=%s reason=%s", item["key"], picked[1]["from"],
                    picked[1]["at"], picked[1]["reason"])
    return [picked[0]], picked[1]


def tick(now: datetime | None = None) -> dict:
    """Execute due actions. Recurring jobs fire their latest due occurrence once
    (no storm after downtime); one-off tasks retry up to max_attempts."""
    now = now or datetime.now(timezone.utc)
    fired = failed = 0
    for item in list_items():
        if item["type"] not in {"task", "job"} or not item.get("action") or item["status"] in {"paused", "failed"}:
            continue
        try:
            since = _parse(item["last_fired"], "UTC") if item.get("last_fired") else now - timedelta(seconds=_tick_seconds() * 2)
            flex_info = None
            if item.get("recurrence") and (item.get("params") or {}).get("flex"):
                due, flex_info = _flex_due(item, since, now)
            else:
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
                _record_run(fresh, str(due[-1].get("occurrence") or ""), ok, detail, now.isoformat(), "agenda", ms,
                            flex=flex_info)
                if ok or fresh.get("recurrence"):
                    fresh["last_fired"] = now.isoformat()
                    fresh["attempts"] = 0
                    if ok and not fresh.get("recurrence"):
                        fresh["status"] = "completed"
                else:
                    fresh["attempts"] = int(fresh.get("attempts") or 0) + 1
                    if fresh["attempts"] >= _max_attempts():
                        fresh["status"] = "failed"
                _save(fresh)
                if fresh["status"] == "failed" and fresh.get("parent"):
                    _mark_parent(fresh, ok=False, detail=f"voce collegata fallita: {fresh['title']}", by="agenda")
            fired += int(ok)
            failed += int(not ok)
            if not ok:
                logger.warning("[🔄] event=agenda_action_failed item=%s detail=%s", item["key"], detail)
        except Exception as exc:
            logger.warning("[🔄] event=agenda_tick_item_error item=%s error=%s", item.get("key"), exc)
    if fired or failed:
        logger.info("event=agenda_tick fired=%d failed=%d", fired, failed)
    return {"fired": fired, "failed": failed}


_TICK_HOOKS: list = []


def on_tick(fn) -> None:
    """Run ``fn()`` after every agenda tick (e.g. presence re-evaluation): no extra loops."""
    _TICK_HOOKS.append(fn)


def start_worker() -> None:
    def _loop():
        while True:
            time.sleep(_tick_seconds())
            try:
                tick()
            except Exception as exc:
                logger.warning("[🔄] event=agenda_worker_error error=%s", exc)
            for hook in list(_TICK_HOOKS):
                try:
                    hook()
                except Exception as exc:
                    logger.warning("[🔄] event=agenda_tick_hook_error hook=%s error=%s",
                                   getattr(hook, "__name__", hook), exc)

    threading.Thread(target=_loop, daemon=True, name="agenda-worker").start()
    logger.info("event=agenda_worker_started tick=%ds", _tick_seconds())


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


# ── Runs view (WebUI plugin «Esecuzioni», SPEC 2026-10-18-moduli-core-e-mcp-esterno §A2) ──────────
RUN_STATUSES = ("ok", "failed", "skipped")


def _run_row(item: dict, *, status: str, at: str, occurrence: str | None, detail: str | None = None,
             by: str | None = None, duration_ms: int | None = None) -> dict:
    return {"item_id": item["id"], "key": item["key"], "title": item["title"], "owner": item["owner"],
            "type": item["type"], "item_status": item["status"], "status": status, "at": at,
            "occurrence": occurrence, "detail": detail, "by": by, "duration_ms": duration_ms,
            "manual": bool(occurrence and str(occurrence).startswith("manual:")),
            "can_run": bool(item.get("action")) and item["status"] not in {"cancelled", "completed"}}


def runs(*, owner: str | None = None, status: str | None = None, since: datetime | None = None,
         limit: int = 100, now: datetime | None = None) -> dict:
    """Every recorded run of jobs/tasks (each item keeps its last runs) + skipped past occurrences,
    newest first, with a summary and the rules registered per owner."""
    if status and status not in RUN_STATUSES:
        raise AgendaError(f"status must be one of {', '.join(RUN_STATUSES)}")
    now = now or datetime.now(timezone.utc)
    items = [_to_item(r) for r in _raw_items()]
    rows: list[dict] = []
    owners: dict[str, dict] = {}
    for item in items:
        o = owners.setdefault(item["owner"], {"owner": item["owner"], "rules": 0, "active": 0, "paused": 0,
                                              "failed": 0, "user_modified": 0, "types": {}})
        o["rules"] += 1
        o["types"][item["type"]] = o["types"].get(item["type"], 0) + 1
        if item["status"] in {"paused", "failed"}:
            o[item["status"]] += 1
        elif item["status"] not in {"cancelled", "completed"}:
            o["active"] += 1
        o["user_modified"] += int(item["user_modified"])
        if owner and item["owner"] != owner:
            continue
        for r in item.get("runs") or []:
            if isinstance(r, dict) and r.get("at"):
                rows.append(_run_row(item, status="ok" if r.get("ok") else "failed", at=str(r["at"]),
                                     occurrence=r.get("occurrence"), detail=r.get("detail"), by=r.get("by"),
                                     duration_ms=r.get("duration_ms")))
        if item["type"] in {"job", "task"}:
            for occ in item.get("skips") or []:
                try:
                    when = _parse(occ, "UTC")
                except (TypeError, ValueError):
                    continue
                if when <= now:
                    rows.append(_run_row(item, status="skipped", at=when.isoformat(), occurrence=occ))

    def _ts(row: dict) -> datetime:
        try:
            return _parse(row["at"], "UTC")
        except (TypeError, ValueError):
            return datetime.min.replace(tzinfo=timezone.utc)

    if since:
        rows = [r for r in rows if _ts(r) >= since]
    rows.sort(key=_ts, reverse=True)
    summary = {s: sum(1 for r in rows if r["status"] == s) for s in RUN_STATUSES}
    durations = [int(r["duration_ms"]) for r in rows if r["duration_ms"] is not None]
    summary["avg_ms"] = int(sum(durations) / len(durations)) if durations else None
    summary["failed_items"] = sum(1 for i in items if i["status"] == "failed" and (not owner or i["owner"] == owner))
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"count": len(rows), "runs": rows[: max(1, min(int(limit), 500))], "summary": summary,
            "owners": sorted(owners.values(), key=lambda o: o["owner"])}


def failed_jobs(since: datetime | None = None, now: datetime | None = None) -> list[dict]:
    """Jobs/tasks whose last run failed (or that stopped as failed) and can run again: «Riprova job» chips."""
    now = now or datetime.now(timezone.utc)
    since = since or now - timedelta(days=1)
    out = []
    for item in (_to_item(r) for r in _raw_items()):
        if item["type"] not in {"job", "task"} or not item.get("action") or item["status"] in {"cancelled", "completed"}:
            continue
        last = item.get("last_result") if isinstance(item.get("last_result"), dict) else None
        failed_now = item["status"] == "failed"
        if not failed_now and not (last and not last.get("ok")):
            continue
        try:
            at = _parse(last["at"], "UTC") if last and last.get("at") else None
        except (TypeError, ValueError):
            at = None
        if not failed_now and (at is None or at < since):
            continue
        out.append({"id": item["key"], "item_id": item["id"], "label": item["title"], "owner": item["owner"],
                    "icon": "refresh", "state": "late", "status": item["status"],
                    "at": last.get("at") if last else None, "detail": (last or {}).get("detail"),
                    "hint": item["owner"]})
    out.sort(key=lambda c: str(c.get("at") or ""), reverse=True)
    return out

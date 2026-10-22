"""Coach contract — every domain module tells the weekly planner what it needs (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §4).

A module becomes a coach with one router and the Hub tag ``coach``:

    from hestia_common.coach import CoachRouter, CoachClient, need

    coach = CoachClient("hercules")
    app.include_router(CoachRouter("hercules", "fitness", "Allenamento", needs=build_needs,
                                   fit=fit_need, placed=on_placed, review=review_week).router)

    def build_needs(start: date, end: date) -> dict:          # {state, needs: [need(...)]}
        return {"state": "1/3 questa settimana",
                "needs": [need("workout.1", "Allenamento Push A", kind="block", minutes=60, min_minutes=30,
                               time_of_day="evening", tags=["effort:3", "workout"], reason="1/3", link="oggi")]}

    coach.done("workout.1")          # the user did it (module data) → Chronos marks the plan item
    coach.changed()                  # needs changed (deload, paused routine…) → Chronos re-plans the rest of the week

Chronos (the planner) reads ``GET /api/coach/needs`` through Hub, places the needs in the user's free time and
tells the module where they landed (``POST /api/coach/placed``). Chronos never reads domain words: it only uses
the generic fields validated here. Everything fails soft: a module that does not answer keeps its last plan.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Callable

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("hestia_common.coach")

KINDS = ("block", "slot", "target")
PERS = ("week", "day")
TIMES_OF_DAY = ("morning", "midday", "afternoon", "evening", "any")
PRIORITIES = ("must", "should", "could")
RELATIONS = ("same_day", "day_after", "before", "after")
NEED_FIELDS = ("id", "title", "kind", "count", "per", "minutes", "min_minutes", "days", "fixed_dates", "time_of_day",
               "not_before", "not_after", "min_gap_days", "not_same_day", "with", "tags", "priority", "reason", "link",
               "value", "unit", "progress")


class NeedError(ValueError):
    pass


def _hhmm(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        h, m = text.split(":")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError
    except ValueError:
        raise NeedError(f"{field} must be HH:MM") from None
    return f"{int(h):02d}:{int(m):02d}"


def validate_need(raw: dict) -> dict:
    """One need in its canonical shape; unknown fields and bad values are refused (``NeedError``)."""
    if not isinstance(raw, dict):
        raise NeedError("a need is an object")
    unknown = sorted(set(raw) - set(NEED_FIELDS))
    if unknown:
        raise NeedError(f"unknown fields: {', '.join(unknown)}")
    nid = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not nid or not title:
        raise NeedError("id and title are required")
    kind = raw.get("kind") or "block"
    if kind not in KINDS:
        raise NeedError(f"kind must be one of {KINDS}")
    per = raw.get("per") or "week"
    if per not in PERS:
        raise NeedError(f"per must be one of {PERS}")
    tod = raw.get("time_of_day") or "any"
    if tod not in TIMES_OF_DAY:
        raise NeedError(f"time_of_day must be one of {TIMES_OF_DAY}")
    prio = raw.get("priority") or "should"
    if prio not in PRIORITIES:
        raise NeedError(f"priority must be one of {PRIORITIES}")
    count = int(raw.get("count") if raw.get("count") is not None else 1)
    if not 0 <= count <= 21:
        raise NeedError("count must be 0..21")
    minutes = int(raw.get("minutes") or 0)
    if kind == "block" and minutes <= 0:
        raise NeedError("a block needs minutes")
    min_minutes = int(raw.get("min_minutes") or minutes)
    if min_minutes > minutes:
        min_minutes = minutes
    days = sorted({int(d) for d in raw.get("days") or []})
    if any(d < 0 or d > 6 for d in days):
        raise NeedError("days are weekdays 0 (Monday) .. 6 (Sunday)")
    fixed = []
    for d in raw.get("fixed_dates") or []:
        try:
            fixed.append(date.fromisoformat(str(d)[:10]).isoformat())
        except ValueError:
            raise NeedError("fixed_dates are ISO dates") from None
    rel = raw.get("with")
    if rel:
        if not isinstance(rel, dict) or not rel.get("tag") or rel.get("relation") not in RELATIONS:
            raise NeedError(f"with needs a tag and a relation in {RELATIONS}")
        rel = {"tag": str(rel["tag"]), "relation": rel["relation"]}
    return {
        "id": nid, "title": title[:120], "kind": kind, "count": count, "per": per, "minutes": minutes,
        "min_minutes": min_minutes, "days": days, "fixed_dates": sorted(set(fixed)), "time_of_day": tod,
        "not_before": _hhmm(raw.get("not_before"), "not_before"), "not_after": _hhmm(raw.get("not_after"), "not_after"),
        "min_gap_days": max(0, int(raw.get("min_gap_days") or 0)),
        "not_same_day": sorted({str(t) for t in raw.get("not_same_day") or []}),
        "with": rel or None, "tags": sorted({str(t) for t in raw.get("tags") or []}), "priority": prio,
        "reason": str(raw.get("reason") or "")[:200], "link": str(raw.get("link") or ""),
        "value": raw.get("value"), "unit": str(raw.get("unit") or ""), "progress": raw.get("progress"),
    }


def need(id: str, title: str, **fields) -> dict:
    """Build and validate a need (see ``NEED_FIELDS``)."""
    return validate_need({"id": id, "title": title, **fields})


def week_bounds(day: date, week_start: int = 0) -> tuple[date, date]:
    """``[start, end)`` of the week containing ``day`` (``week_start`` 0 = Monday)."""
    start = day - timedelta(days=(day.weekday() - week_start) % 7)
    return start, start + timedelta(days=7)


def _parse_day(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field} must be an ISO date") from None


class FitRequest(BaseModel):
    need_id: str
    date: str
    minutes: int = Field(..., ge=1, le=600)


class PlacedItem(BaseModel):
    need_id: str
    key: str
    start_at: str
    end_at: str | None = None
    kind: str = "block"
    status: str = "planned"


class PlacedRequest(BaseModel):
    week: str
    items: list[PlacedItem] = Field(default_factory=list)


class CoachRouter:
    """``/api/coach/*`` for one module. ``needs(start, end)`` is required; the others are optional:

    - ``fit(need_id, day, minutes)`` → ``{ok, minutes, title, note}`` a shorter variant (blocks with min_minutes);
    - ``placed(week, items)`` → anything; the module learns where its needs landed;
    - ``review(start, end)`` → ``{done, missed, adherence, notes}`` of a past week (also the module's *signals*).
    """

    def __init__(self, module: str, domain: str, label: str, *, needs: Callable[[date, date], dict],
                 fit: Callable[[str, date, int], dict] | None = None,
                 placed: Callable[[str, list[dict]], Any] | None = None,
                 review: Callable[[date, date], dict] | None = None):
        self.module, self.domain, self.label = module, domain, label
        self._needs, self._fit, self._placed, self._review = needs, fit, placed, review
        self.router = APIRouter()
        self.router.add_api_route("/api/coach/needs", self.get_needs, methods=["GET"])
        self.router.add_api_route("/api/coach/fit", self.post_fit, methods=["POST"])
        self.router.add_api_route("/api/coach/placed", self.post_placed, methods=["POST"])
        self.router.add_api_route("/api/coach/review", self.get_review, methods=["GET"])

    def _head(self) -> dict:
        return {"module": self.module, "domain": self.domain, "label": self.label}

    def get_needs(self, start: str | None = None, end: str | None = None) -> dict:
        frm = _parse_day(start, "start") or date.today()
        to = _parse_day(end, "end") or frm + timedelta(days=7)
        raw = self._needs(frm, to) or {}
        out, refused = [], []
        for n in raw.get("needs") or []:
            try:
                out.append(validate_need(n))
            except NeedError as exc:
                refused.append({"id": (n or {}).get("id") if isinstance(n, dict) else None, "error": str(exc)})
                logger.warning("[🔄] event=coach_need_refused module=%s error=%s", self.module, exc)
        return {**self._head(), "start": frm.isoformat(), "end": to.isoformat(),
                "state": str(raw.get("state") or "")[:300], "needs": out, "refused": refused}

    def post_fit(self, req: FitRequest) -> dict:
        if not self._fit:
            return {"ok": False, "reason": "no shorter variant"}
        day = _parse_day(req.date, "date")
        res = self._fit(req.need_id, day, req.minutes) or {}
        return {"ok": bool(res.get("ok")), **{k: v for k, v in res.items() if k != "ok"}}

    def post_placed(self, req: PlacedRequest) -> dict:
        if self._placed:
            self._placed(req.week, [i.model_dump() for i in req.items])
        return {"ok": True, "count": len(req.items)}

    def get_review(self, start: str | None = None, end: str | None = None) -> dict:
        to = _parse_day(end, "end") or date.today()
        frm = _parse_day(start, "start") or to - timedelta(days=7)
        res = (self._review(frm, to) if self._review else {}) or {}
        return {**self._head(), "start": frm.isoformat(), "end": to.isoformat(),
                "done": int(res.get("done") or 0), "missed": int(res.get("missed") or 0),
                "adherence": res.get("adherence"), "notes": [str(n)[:200] for n in res.get("notes") or []][:10]}


class CoachClient:
    """What a module tells the planner (Chronos ``/api/agenda/coach/report``) — push, never polled. Fails soft."""

    def __init__(self, module: str, hub_api_url: str | None = None):
        self.module = module
        self.hub = (hub_api_url or os.getenv("HUB_API_URL", "http://hestia_hub:19001/api")).rstrip("/")

    def _report(self, body: dict) -> bool:
        try:
            resp = requests.post(f"{self.hub}/route/chronos/api/agenda/coach/report",
                                 json={"method": "POST", "headers": {}, "query": {},
                                       "body": {"module": self.module, **body}, "timeout_seconds": 10},
                                 timeout=13)
            resp.raise_for_status()
            return int((resp.json() or {}).get("status_code", 500)) < 400
        except Exception as exc:
            logger.warning("[🔄] event=coach_report_failed module=%s event_type=%s error=%s",
                           self.module, body.get("event"), exc)
            return False

    @staticmethod
    def _at(at: datetime | str | None) -> str | None:
        return at.isoformat() if isinstance(at, datetime) else at

    def done(self, need_id: str, at: datetime | str | None = None) -> bool:
        """The user did ``need_id`` (logged in the module): the nearest plan item becomes done."""
        return self._report({"event": "done", "need_id": need_id, "at": self._at(at)})

    def skipped(self, need_id: str, at: datetime | str | None = None, reason: str = "") -> bool:
        """The user skipped it: the item is skipped and the rest of the week is re-planned."""
        return self._report({"event": "skipped", "need_id": need_id, "at": self._at(at), "reason": reason[:200]})

    def changed(self) -> bool:
        """The module's needs changed (deload, paused routine…): re-plan the rest of the week."""
        return self._report({"event": "changed"})

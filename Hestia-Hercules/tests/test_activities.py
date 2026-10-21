"""Hercules outdoor activities (dossier 2026-10-20-meteo-hecate §3.8): slot picker, propose → confirm →
calendar «Allenamenti» + agenda question, outcome, log, morning coach line. Fake Hub (Hecate/Hermes) + fake agenda.

Markers: unit
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core import activities as act
from app.core.activities import Activities
from app.core.service import Hercules
from app.core.store import Store

from tests.test_hercules import FakeArchive

pytestmark = pytest.mark.unit


def _hour(day: str, h: int, *, rain=0, temp=15.0, wind=5):
    return {"time": f"{day}T{h:02d}:00", "temp_c": temp, "feels_c": temp, "rain_prob": rain, "rain_mm": 0,
            "wind_kmh": wind, "is_day": 6 <= h < 20, "condition": "Sereno", "icon": "sun"}


class FakeHub:
    """Hecate (forecast, events, calendars) and Hermes as the Hub would route them."""

    def __init__(self, today):
        self.today = today
        self.calls: list[tuple] = []
        self.busy: list[dict] = []
        self.rainy: set[str] = set()          # "YYYY-MM-DD" fully rainy
        self.weather_down = False
        self.events: dict[str, dict] = {}

    def forecast(self, d0: str, d1: str) -> dict:
        days, d = [], datetime.fromisoformat(d0).date()
        while d.isoformat() <= d1:
            ds = d.isoformat()
            days.append({"date": ds, "sunrise": "06:30", "sunset": "20:00",
                         "hours": [_hour(ds, h, rain=90 if ds in self.rainy else 0) for h in range(24)]})
            d += timedelta(days=1)
        return {"status": "ok", "place": {"label": "Casa"}, "days": days}

    def __call__(self, service, method, path, *, body=None, query=None, timeout=8):
        self.calls.append((service, method, path, body, query))
        if service == "hecate" and path == "api/gateway/weather/forecast":
            if self.weather_down:
                return 503, {"detail": "down"}
            return 200, self.forecast(query["date_from"], query["date_to"])
        if service == "hecate" and path == "api/gateway/calendar/events" and method == "GET":
            return 200, {"events": self.busy}
        if service == "hecate" and path == "api/gateway/calendar/calendars":
            return 200, {"status": "ok", "calendar_id": "cal-allenamenti"}
        if service == "hecate" and path == "api/gateway/calendar/events" and method == "POST":
            eid = f"ev{len(self.events) + 1}"
            self.events[eid] = body
            return 200, {"results": [{"provider": "google", "success": True, "event_id": eid}]}
        if service == "hecate" and path.startswith("api/gateway/calendar/events/"):
            eid = path.rsplit("/", 1)[1]
            if method == "DELETE":
                self.events.pop(eid, None)
            else:
                self.events[eid]["event"].update(body["updates"])
            return 200, {"success": True}
        if service == "hermes":
            return 200, {"status": "ok"}
        raise AssertionError(f"unexpected call {service} {method} {path}")

    def of(self, service, path_part, method=None):
        return [c for c in self.calls if c[0] == service and path_part in c[2] and (method is None or c[1] == method)]


class FakeAgenda:
    def __init__(self):
        self.planned, self.cancelled, self.finished = {}, [], []

    def plan(self, key, title, start_at, **kw):
        self.planned[key] = {"title": title, "start_at": start_at, **kw}

    def cancel(self, key):
        self.cancelled.append(key)

    def done(self, key):
        self.finished.append(key)


@pytest.fixture
def env():
    h = Hercules(Store(FakeArchive(), min_refresh_seconds=0), lambda key: None, tz_name="Europe/Rome")
    hub = FakeHub(h.today())
    ag = FakeAgenda()
    return h, hub, ag, Activities(h, hub, ag, api="/api/hercules")


# ── pure picker ─────────────────────────────────────────────────────────────
def test_score_hour_rain_dark_and_good():
    day = "2026-10-21"
    assert act.score_hour(_hour(day, 18, rain=80))[0] == 0
    assert act.score_hour(_hour(day, 22), sunrise="06:30", sunset="20:00")[0] == 0
    good, why = act.score_hour(_hour(day, 18), sunrise="06:30", sunset="20:00")
    assert good >= act.GOOD_SCORE and "asciutto" in why
    windy, _ = act.score_hour(_hour(day, 18, wind=50), sunrise="06:30", sunset="20:00")
    assert windy < good


def test_pick_slots_spaces_days_when_possible():
    c = [{"start": f"2026-10-{d:02d}T18:00:00+02:00", "score": s} for d, s in ((20, 90), (21, 89), (23, 70), (24, 60))]
    picked = act.pick_slots(c, 2)
    assert [p["start"][:10] for p in picked] == ["2026-10-20", "2026-10-23"]
    assert len(act.pick_slots(c[:2], 2)) == 2            # no choice left: back-to-back is fine


def test_best_of_day_skips_busy_hours():
    day = "2026-10-21"
    hours = [_hour(day, h) for h in range(24)]
    tz = None
    busy = [(datetime.fromisoformat(f"{day}T{h:02d}:00"), datetime.fromisoformat(f"{day}T{h + 1:02d}:00"))
            for h in range(6, 20) if h != 9]
    best = act.best_of_day(day, hours, minutes=45, busy=busy, sunrise="06:30", sunset="20:00", tz=tz)
    assert best["start"].startswith(f"{day}T09:00")


def test_kind_aliases():
    assert act.kind_of("correre") == "corsa" and act.kind_of("bike") == "bici" and act.kind_of("") == "corsa"
    assert act.kind_of("yoga") == "altro"


# ── propose / confirm ───────────────────────────────────────────────────────
def test_propose_writes_nothing_to_the_calendar(env):
    h, hub, ag, a = env
    out = a.propose("correre", times=2, week="next")
    assert out["kind"] == "Corsa" and len(out["slots"]) == 2
    assert not hub.of("hecate", "calendar/events", "POST") and not hub.of("hecate", "calendars")
    assert not ag.planned
    plan = h.store.data("activity_plan", out["plan_id"])
    assert plan["status"] == "proposed" and all(s["status"] == "proposed" for s in plan["slots"])


def test_propose_avoids_rainy_days(env):
    h, hub, ag, a = env
    d0, d1 = a._week("next")
    d = d0
    while d <= d1:
        if d.weekday() != 2:
            hub.rainy.add(d.isoformat())
        d += timedelta(days=1)
    out = a.propose("corsa", times=2, week="next")
    assert len(out["slots"]) == 1 and datetime.fromisoformat(out["slots"][0]["start"]).weekday() == 2
    assert "Solo 1" in out["hint"]


def test_propose_without_weather_keeps_the_intention(env):
    h, hub, ag, a = env
    hub.weather_down = True
    out = a.propose("corsa", times=2)
    assert out["slots"] == [] and out["weather"] == "unavailable" and "intenzione" in out["hint"]


def test_confirm_creates_events_in_allenamenti_and_the_question(env):
    h, hub, ag, a = env
    p = a.propose("corsa", times=2, week="next")
    out = a.confirm(p["plan_id"], ["1"])
    assert out["confirmed"] and len(out["planned"]) == 1
    (ev,) = hub.events.values()
    assert ev["calendar_id"] == "cal-allenamenti" and ev["nag"] is False and ev["event"]["title"] == "Corsa"
    assert hub.of("hecate", "calendars")[0][3] == {"name": "Allenamenti", "provider": "google"}
    (key, item), = ag.planned.items()
    plan = h.store.data("activity_plan", p["plan_id"])
    slot = next(s for s in plan["slots"] if s["status"] == "planned")
    assert key == f"hercules.activity.{slot['id']}"
    assert item["action"]["path"].endswith(f"/activities/{plan['id']}/slots/{slot['id']}/ask")
    assert [s["status"] for s in plan["slots"]].count("cancelled") == 1


def test_confirm_with_a_time_chosen_by_the_user(env):
    h, hub, ag, a = env
    p = a.propose("bici", times=1, week="next")
    when = (datetime.combine(a._week("next")[0], datetime.min.time()) + timedelta(hours=19)).isoformat()
    a.confirm(p["plan_id"], [when])
    plan = h.store.data("activity_plan", p["plan_id"])
    planned = [s for s in plan["slots"] if s["status"] == "planned"]
    assert len(planned) == 1 and planned[0]["start"].startswith(when[:16]) and planned[0]["why"] == ["scelto da te"]


# ── outcome ─────────────────────────────────────────────────────────────────
def _confirmed(a, h):
    p = a.propose("corsa", times=1, week="next")
    a.confirm(p["plan_id"])
    plan = h.store.data("activity_plan", p["plan_id"])
    return plan, next(s for s in plan["slots"] if s["status"] == "planned")


def test_ask_then_done_logs_marks_event_and_closes_the_question(env):
    h, hub, ag, a = env
    plan, slot = _confirmed(a, h)
    msg = a.ask(plan["id"], slot["id"])
    assert msg["key"] == f"hercules.activity.{slot['id']}" and [x["id"] for x in msg["actions"]] == ["done", "missed", "moved"]
    assert all(x["resolves"] for x in msg["actions"])
    out = a.slot_done(plan["id"], slot["id"], km=5)
    assert out["done"] == 1 and out["hint"] == "Corsa 1/1"
    (ev,) = hub.events.values()
    assert ev["event"]["title"] == "Corsa ✓"
    assert f"hercules.activity.{slot['id']}" in ag.finished
    closes = [c for c in hub.of("hermes", "events/ingest") if c[3]["payload"].get("closes")]
    assert closes and closes[-1][3]["payload"]["closes"] == msg["key"]
    assert a.ask(plan["id"], slot["id"]) is None             # answered: nothing more to ask
    assert len(a.logs()) == 1 and a.logs()[0]["km"] == 5


def test_moved_replans_on_another_day(env):
    h, hub, ag, a = env
    plan, slot = _confirmed(a, h)
    out = a.slot_moved(plan["id"], slot["id"])
    assert out["moved"] and out.get("planned")
    plan = h.store.data("activity_plan", plan["id"])
    new = [s for s in plan["slots"] if s["status"] == "planned"]
    assert len(new) == 1 and new[0]["start"][:10] != slot["start"][:10]
    assert f"hercules.activity.{slot['id']}" in ag.cancelled and len(hub.events) == 1


def test_missed_marks_the_event(env):
    h, hub, ag, a = env
    plan, slot = _confirmed(a, h)
    assert a.slot_missed(plan["id"], slot["id"])["done"] == 0
    assert next(iter(hub.events.values()))["event"]["title"] == "Corsa ✗"


def test_log_without_plan_goes_to_history_and_unlog_removes_it(env):
    h, hub, ag, a = env
    out = a.log("camminata", minutes=40)
    assert out["logged"] and out["kind"] == "Camminata"
    (ev,) = hub.events.values()
    assert ev["event"]["title"] == "Camminata ✓" and ev["calendar_id"] == "cal-allenamenti"
    a.unlog(out["id"])
    assert not hub.events and not a.logs()


def test_log_closes_a_planned_slot_of_that_day(env):
    h, hub, ag, a = env
    plan, slot = _confirmed(a, h)
    out = a.log("corsa", day=slot["start"][:10], km=6)
    assert out["done"] == 1 and "slot" in out
    a.unlog(a.logs()[0]["id"])                               # undo puts the slot back
    plan = h.store.data("activity_plan", plan["id"])
    assert next(s for s in plan["slots"] if s["id"] == slot["id"])["status"] == "planned"


def test_sync_sessions_is_idempotent(env):
    h, hub, ag, a = env
    start = datetime.now(h.tz) - timedelta(hours=2)
    h.store.write([{"kind": "session", "id": "s1", "data": {"status": "done", "name": "Push A",
                    "started_at": start.isoformat(), "ended_at": (start + timedelta(hours=1)).isoformat()}}])
    assert a.sync_sessions() == 1 and a.sync_sessions() == 0
    assert next(iter(hub.events.values()))["event"]["title"] == "Push A"


# ── morning coach line ──────────────────────────────────────────────────────
def test_morning_good_day_once_per_day(env):
    h, hub, ag, a = env
    today = h.today()
    if datetime.now(h.tz).hour >= 18:
        pytest.skip("late in the day: no window left today")
    p = a.propose("corsa", times=2)
    a.confirm(p["plan_id"], [])                              # intention only, no slot kept
    plan = h.store.data("activity_plan", p["plan_id"])
    plan.update(status="confirmed", slots=[])
    h.save("activity_plan", plan, id=plan["id"])
    msg = a.morning()
    assert msg and msg["text"].startswith("Ottimo giorno per la corsa") and "Corsa 0/2" in msg["text"]
    assert msg["actions"][0]["path"].endswith(f"/activities/{plan['id']}/slots")
    assert msg["actions"][0]["body"]["start"].startswith(today.isoformat())
    a.mark_nudge()
    assert a.morning() == {"skip": "sent_today"}


def test_morning_rain_on_todays_slot_offers_to_move(env):
    h, hub, ag, a = env
    if datetime.now(h.tz).hour >= 18:
        pytest.skip("late in the day")
    today = h.today().isoformat()
    p = a.propose("corsa", times=1)
    plan = h.store.data("activity_plan", p["plan_id"])
    start = datetime.fromisoformat(f"{today}T19:00").replace(tzinfo=h.tz)
    plan.update(status="confirmed", slots=[{"id": "x1", "status": "planned", "start": start.isoformat(),
                                             "end": (start + timedelta(minutes=45)).isoformat()}])
    h.save("activity_plan", plan, id=plan["id"])
    hub.rainy.add(today)
    msg = a.morning()
    assert msg["text"].startswith("Pioggia alle 19:00") and [x["id"] for x in msg["actions"]] == ["move", "keep"]


def test_morning_silent_without_open_intention(env):
    h, hub, ag, a = env
    assert a.morning() is None

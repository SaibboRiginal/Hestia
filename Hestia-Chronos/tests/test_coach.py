"""Weekly coach plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §5, §14). Archive, Hub and modules mocked."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from hestia_common.coach import need, validate_need, NeedError

TZ = ZoneInfo("Europe/Rome")
MON = date(2026, 10, 19)
WEEK = [MON + timedelta(days=i) for i in range(7)]


def _free(busy=None, start=time(7), end=time(22), buffer=15):
    from services.coach_planner import free_intervals
    return {d: free_intervals(d, start, end, (busy or {}).get(d, []), TZ, buffer) for d in WEEK}


def _at(d, h, m=0):
    return datetime.combine(d, time(h, m), tzinfo=TZ)


def _workouts(count=3, **kw):
    return {**need("workout", "Allenamento", kind="block", count=count, minutes=60, min_minutes=30,
                   time_of_day="evening", min_gap_days=2, tags=["effort:3", "workout"], **kw), "module": "hercules"}


def _routines():
    return [{**need("routine.acid", "Esfoliante", kind="slot", count=2, time_of_day="evening", min_gap_days=2,
                    tags=["skin.acid"], not_same_day=["skin.retinoid"]), "module": "hygieia"},
            {**need("routine.retinol", "Retinolo", kind="slot", count=2, time_of_day="evening", min_gap_days=2,
                    tags=["skin.retinoid"]), "module": "hygieia"}]


# ── contract ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_need_validation_refuses_unknown_and_bad_fields():
    assert validate_need({"id": "a", "title": "A", "kind": "slot"})["count"] == 1
    for bad in ({"id": "a", "title": "A", "colour": "red"}, {"id": "a", "title": "A", "kind": "block"},
                {"id": "a", "title": "A", "days": [7]}, {"id": "a", "title": "A", "not_before": "25:00"},
                {"id": "a", "title": "A", "with": {"tag": "x", "relation": "near"}}, {"title": "A"}):
        with pytest.raises(NeedError):
            validate_need(bad)
    n = need("w", "W", kind="block", minutes=40, min_minutes=60)
    assert n["min_minutes"] == 40          # never longer than the full version


@pytest.mark.api
def test_coach_router_validates_module_needs():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hestia_common.coach import CoachRouter
    app = FastAPI()
    app.include_router(CoachRouter("demo", "demo", "Demo", needs=lambda s, e: {
        "state": "ok", "needs": [{"id": "x", "title": "X", "kind": "slot"}, {"id": "y", "title": "Y", "bad": 1}]},
        fit=lambda nid, d, m: {"ok": True, "minutes": m, "title": "corto"}).router)
    c = TestClient(app)
    body = c.get("/api/coach/needs", params={"start": "2026-10-19", "end": "2026-10-26"}).json()
    assert [n["id"] for n in body["needs"]] == ["x"] and body["refused"][0]["id"] == "y"
    assert c.post("/api/coach/fit", json={"need_id": "x", "date": "2026-10-20", "minutes": 30}).json() == \
        {"ok": True, "minutes": 30, "title": "corto"}
    assert c.get("/api/coach/review").json()["done"] == 0


# ── planner (pure) ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_full_tuesday_conflicting_routines_and_spread_workouts():
    """Acceptance 1: three workouts on spaced free evenings, never Tuesday; conflicting routines never together."""
    from services.coach_planner import plan_week
    busy = {WEEK[1]: [(_at(WEEK[1], 8), _at(WEEK[1], 22, 30))]}
    plan = plan_week(WEEK, _free(busy), [_workouts(), *_routines()], tz=TZ)
    work = sorted(i["date"] for i in plan["items"] if i["need_id"] == "workout")
    assert len(work) == 3 and WEEK[1] not in work
    assert all((b - a).days >= 2 for a, b in zip(work, work[1:]))
    by_day: dict = {}
    for i in plan["items"]:
        by_day.setdefault(i["date"], set()).add(i["need_id"])
    assert not any({"routine.acid", "routine.retinol"} <= ids for ids in by_day.values())
    assert plan["unplaced"] == []
    assert plan == plan_week(WEEK, _free(busy), [_workouts(), *_routines()], tz=TZ)   # deterministic


@pytest.mark.unit
def test_short_day_asks_the_module_for_a_shorter_variant():
    """Acceptance 2: only 40 free minutes → the module's short version."""
    from services.coach_planner import plan_week
    days = [MON]
    busy = {MON: [(_at(MON, 7), _at(MON, 21, 5))]}
    asked = []

    def fit(module, nid, d, minutes):
        asked.append((module, nid, minutes))
        return {"ok": True, "minutes": 35, "title": "Allenamento corto"}

    plan = plan_week(days, {MON: _free(busy, buffer=0)[MON]}, [_workouts(count=1)], tz=TZ, fit=fit)
    assert asked == [("hercules", "workout", 55)]
    item = plan["items"][0]
    assert item["minutes"] == 35 and item["variant"]["minutes"] == 35 and item["title"] == "Allenamento corto"


@pytest.mark.unit
def test_what_does_not_fit_is_unplaced_with_a_reason():
    from services.coach_planner import plan_week
    busy = {d: [(_at(d, 7), _at(d, 22))] for d in WEEK}
    plan = plan_week(WEEK, _free(busy), [_workouts()], tz=TZ)
    assert plan["items"] == [] and plan["unplaced"][0]["missing"] == 3 and plan["unplaced"][0]["reason"]


@pytest.mark.unit
def test_relation_and_daily_limits_and_kept_items():
    from services.coach_planner import PlannerConfig, plan_week
    supp = {**need("supp", "Integratore", kind="slot", count=3, **{"with": {"tag": "workout", "relation": "same_day"}}),
            "module": "hygieia"}
    kept = [{"module": "hercules", "need_id": "workout", "kind": "block", "title": "Allenamento", "date": WEEK[3],
             "start": _at(WEEK[3], 18).isoformat(), "start_dt": _at(WEEK[3], 18), "end_dt": _at(WEEK[3], 19),
             "tags": ["workout"]}]
    plan = plan_week(WEEK, _free(), [_workouts(), supp], keep=kept, tz=TZ, cfg=PlannerConfig(max_blocks_per_day=1))
    work = sorted(i["date"] for i in plan["items"] if i["need_id"] == "workout") + [WEEK[3]]
    assert len(work) == 3                                   # the kept one counts
    supp_days = {i["date"] for i in plan["items"] if i["need_id"] == "supp"}
    assert supp_days <= set(work) and len(supp_days) == 3
    assert WEEK[3] not in {i["date"] for i in plan["items"] if i["need_id"] == "workout"}


@pytest.mark.unit
def test_outdoor_needs_avoid_rainy_and_dark_hours():
    """Weather dossier 2026-10-20-meteo-hecate: an ``outdoor`` need is not placed where it rains; others are."""
    from services.coach import wet_hours
    from services.coach_planner import plan_week
    days = []
    for d in WEEK:
        rain_all_day = d.weekday() < 6                      # only Sunday is dry
        days.append({"date": d.isoformat(), "hours": [
            {"time": f"{d.isoformat()}T{h:02d}:00", "rain_prob": 90 if rain_all_day else 0, "rain_mm": 0,
             "is_day": 7 <= h < 19} for h in range(24)]})
    wet = wet_hours(days, TZ)
    assert len(wet[WEEK[0]]) == 24 and len(wet[WEEK[6]]) == 12        # Sunday: only the dark hours
    run = {**need("activity.p1", "Corsa", kind="block", count=2, minutes=45, min_minutes=45, time_of_day="any",
                  min_gap_days=1, tags=["outdoor", "effort:2"], priority="could"), "module": "hercules"}
    gym = _workouts(1)
    plan = plan_week(WEEK, _free(), [run, gym], tz=TZ, wet=wet)
    runs = [i for i in plan["items"] if i["need_id"] == "activity.p1"]
    assert len(runs) == 1 and runs[0]["date"] == WEEK[6]
    assert 7 <= datetime.fromisoformat(runs[0]["start"]).hour < 19
    assert plan["unplaced"][0]["reason"] == "pioggia o buio nei momenti liberi"
    assert any(i["need_id"] == "workout" and i["date"] != WEEK[6] for i in plan["items"])   # indoor: rain is fine
    assert len([i for i in plan_week(WEEK, _free(), [run], tz=TZ)["items"]]) == 2           # no forecast: no filter


@pytest.mark.unit
def test_planner_has_no_domain_words():
    """Acceptance 8: the planner reads the contract only."""
    import inspect
    from services import coach_planner
    src = inspect.getsource(coach_planner).lower()
    for word in ("hercules", "hygieia", "plutus", "retinol", "palestra", "allenamento", "fitness", "selfcare"):
        assert word not in src


# ── orchestration (Chronos) ─────────────────────────────────────────────────


@pytest.fixture
def chronos():
    from services import agenda as A
    from services import coach as C
    rows: dict = {}

    def route_archive(method, path, body=None, query=None, timeout=10):
        if method == "GET":
            return list(rows.values())
        row = {**body, "id": body["external_id"]}
        rows[body["external_id"]] = row
        return row

    events: list[dict] = []
    modules = {"hercules": {"needs": [{"id": "workout", "title": "Allenamento", "kind": "block", "count": 3,
                                       "minutes": 60, "min_minutes": 30, "time_of_day": "evening",
                                       "min_gap_days": 2, "tags": ["workout", "effort:3"]}]}}
    calls: list = []

    def route(service, method, path, query=None, body=None, timeout=15):
        calls.append((service, method, path, body))
        if service == "oracle":
            return 503, {"detail": "down"}
        if path == "api/coach/needs":
            return 200, {"module": service, "label": "Allenamento", "domain": "fitness", "state": "0/3",
                         "needs": [validate_need(n) for n in modules[service]["needs"]]}
        if path == "api/coach/review":
            return 200, {"module": service, "label": "Allenamento", "done": 2, "missed": 1, "notes": []}
        return 200, {"ok": True}

    sent: list = []
    now = {"value": _at(MON, 9)}
    with patch.object(A.archive_client, "_route_archive", side_effect=route_archive), \
            patch.object(C.archive_client, "list_items", side_effect=lambda **kw: list(events)), \
            patch.object(C, "coaches", return_value=["hercules"]), \
            patch.object(C, "_route", side_effect=route), \
            patch.object(C, "now", side_effect=lambda: now["value"]), \
            patch.object(C.hermes_client, "publish_event", side_effect=lambda *a: sent.append(a) or True), \
            patch.object(C, "schedule_replan", side_effect=lambda reason, day=None: C.replan(day, reason=reason)):
        yield {"C": C, "rows": rows, "events": events, "modules": modules, "calls": calls, "sent": sent, "now": now}


def _workout_days(C):
    plan = C.view(MON)
    return [d["date"] for d in plan["days"] for i in d["items"] if i["need_id"] == "workout" and i["status"] == "planned"]


@pytest.mark.unit
def test_replan_writes_plan_items_and_tells_the_module(chronos):
    C = chronos["C"]
    plan = C.replan(MON, reason="manual")
    days = _workout_days(C)
    assert len(days) == 3 and plan["week"] == "2026-10-19"
    placed = [c for c in chronos["calls"] if c[2] == "api/coach/placed"]
    assert placed and len(placed[-1][3]["items"]) == 3
    assert all(r["meta"]["owner"] == "hercules" for k, r in chronos["rows"].items() if k.startswith("coach.2026"))


@pytest.mark.unit
def test_calendar_event_over_a_block_moves_it_and_notifies_only_today_or_tomorrow(chronos):
    """Acceptance 3."""
    C = chronos["C"]
    C.replan(MON, reason="manual")
    first = _workout_days(C)[0]
    assert first == "2026-10-19"
    chronos["events"].append({"source": "google", "start_at": _at(MON, 16).isoformat(), "end_at": _at(MON, 23).isoformat()})
    assert C.on_calendar_synced(MON) is True
    days = _workout_days(C)
    assert "2026-10-19" not in days and len(days) == 3
    assert chronos["sent"] and chronos["sent"][-1][2] == "coach.change"


@pytest.mark.unit
def test_done_report_marks_the_item_and_user_moves_are_kept(chronos):
    """Acceptance 4 and 5."""
    C = chronos["C"]
    C.replan(MON, reason="manual")
    key = next(k for k, r in chronos["rows"].items() if k.endswith(".workout.2026-10-19"))
    chronos["now"]["value"] = _at(MON, 19)
    res = C.report("hercules", "done", "workout", _at(MON, 18, 30).isoformat())
    assert res["matched"] == key and chronos["rows"][key]["status"] == "completed"
    moved_key = next(k for k, r in chronos["rows"].items() if k.startswith("coach.2026") and r["status"] == "confirmed"
                     and not k.endswith("2026-10-19"))
    C.move(moved_key, _at(WEEK[6], 10).isoformat())
    chronos["modules"]["hercules"]["needs"][0]["count"] = 2      # one done: two still to do
    C.replan(MON + timedelta(days=1), reason="changed")
    assert chronos["rows"][moved_key]["start_at"].startswith("2026-10-25T10:00")
    assert chronos["rows"][moved_key]["status"] == "confirmed"


@pytest.mark.unit
def test_weekly_message_without_the_brain_uses_the_fixed_text(chronos):
    """Acceptance 6."""
    C = chronos["C"]
    chronos["now"]["value"] = _at(WEEK[6], 18)
    out = C.run_week()
    assert out["week"] == "2026-10-26" and out["delivered"] is True
    assert out["text"].startswith("Piano della settimana:") and "Allenamento" in out["text"]
    domain, event_type, entity, payload = chronos["sent"][-1]
    assert domain == "system" and entity == "coach.week" and payload["_link"]["page"] == "settimana"


@pytest.mark.unit
def test_skip_does_not_bring_the_need_back_the_same_day(chronos):
    C = chronos["C"]
    C.replan(MON, reason="manual")
    key = next(k for k in chronos["rows"] if k.endswith(".workout.2026-10-19"))
    C.skip(key)
    assert chronos["rows"][key]["status"] == "cancelled"
    assert "2026-10-19" not in _workout_days(C) and len(_workout_days(C)) == 3


@pytest.mark.api
def test_endpoints(chronos):
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    assert c.post("/api/agenda/coach/replan", json={"date": "2026-10-19"}).status_code == 200
    week = c.get("/api/agenda/coach/week", params={"date": "2026-10-21"}).json()
    assert week["week"] == "2026-10-19" and len(week["days"]) == 7
    assert c.get("/api/agenda/coach/today").json()["date"] == "2026-10-19"
    assert c.post("/api/agenda/coach/report", json={"module": "hercules", "event": "nope"}).status_code == 400
    busy = c.post("/api/agenda/coach/busy", json={"start_at": "2026-10-21T00:00:00+02:00",
                                                  "end_at": "2026-10-22T23:59:00+02:00", "title": "Trasferta"})
    assert busy.status_code == 200
    days = _workout_days(chronos["C"])
    assert not {"2026-10-21", "2026-10-22"} & set(days)
    assert c.get("/api/agenda/coach/review", params={"date": "2026-10-26"}).json()["modules"][0]["done"] == 2

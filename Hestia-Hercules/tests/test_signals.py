"""Reflection signals (docs/work/2026-10-20-riflessione-a-livelli): signals, weekly metrics, context topic and the
agenda endpoint, over the fake Archive store of ``test_hercules``. No network: the signals transport is mocked.

Markers: unit, api
"""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core import catalog
from app.core import signals as sig
from app.core.service import Hercules
from app.core.store import Store

from .test_hercules import FakeArchive

TZ = ZoneInfo("Europe/Rome")
BENCH = catalog.exercise_id("bench_press")
SQUAT = catalog.exercise_id("back_squat")


def _at(day, hour=18):
    return datetime.combine(day, time(hour), TZ).astimezone(timezone.utc).isoformat()


def _workout(h, started_at, sets):
    s = h.start_session(name="Libero", started_at=started_at)
    for ex_id, w, reps in sets:
        h.log_set(s["id"], {"exercise_id": ex_id, "weight_kg": w, "reps": reps})
    h.finish_session(s["id"], ended_at=started_at)
    return s["id"]


@pytest.fixture
def hc():
    h = Hercules(Store(FakeArchive(), min_refresh_seconds=0), lambda key: None, tz_name="Europe/Rome")
    h.ensure_catalog()
    return h


@pytest.fixture
def trained(hc):
    """11 weekly bench sessions at the same load (stall), squat 11 weeks ago and a heavier squat today (PR), a weekly
    program on every day (missed in a row since the last bench), three low-energy check-ins this week."""
    today = hc.today()
    tpl = hc.save_template({"name": "Full", "items": [{"exercise_id": BENCH, "sets": [{"reps_min": 6, "reps_max": 8}]}]})
    hc.save("program", {"name": "Ogni giorno", "mode": "weekly", "active": True,
                        "days": [{"weekday": d, "template_id": tpl["id"]} for d in range(7)]})
    for k in range(11, 0, -1):
        sets = [(BENCH, 80, 8), (BENCH, 80, 8)] + ([(SQUAT, 100, 5)] if k == 11 else [])
        _workout(hc, _at(today - timedelta(days=7 * k)), sets)
    _workout(hc, (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), [(SQUAT, 110, 5)])
    for i in range(3):
        hc.checkin({"energy": 1, "sleep": 2, "at": (datetime.now(timezone.utc) - timedelta(hours=1 + 20 * i)).isoformat()})
    return hc


@pytest.mark.unit
def test_signals_keys_on_fake_data(trained):
    signals, _ = trained.signals()
    by_key = {s["key"]: s for s in signals}
    assert f"stall:{BENCH}" in by_key and by_key[f"stall:{BENCH}"]["severity"] == "attenzione"
    assert by_key[f"stall:{BENCH}"]["kind"] == "trend" and by_key[f"stall:{BENCH}"]["page"] == f"esercizi/{BENCH}"
    assert by_key["deload"]["severity"] == "attenzione"
    assert by_key["missed_streak"]["kind"] == "streak" and by_key["missed_streak"]["severity"] == "alta"   # 6 days
    pr = by_key[f"pr:{SQUAT}"]
    assert pr["kind"] == "milestone" and pr["severity"] == "info" and pr["ttl_days"] == 3
    for s in signals:   # user text speaks of the domain, never the module
        assert "hercules" not in s["text"].lower() and s["text"]


@pytest.mark.unit
def test_no_data_no_signals(hc):
    assert hc.signals() == ([], [])


@pytest.mark.unit
def test_missed_streak_severity_and_skipped_days(trained):
    today = trained.today()
    # a skipped day is the user's decision: it neither counts nor breaks the streak
    trained.skip_day((today - timedelta(days=1)).isoformat())
    assert len(sig.missed_streak(trained, today)) == 5
    _workout(trained, _at(today - timedelta(days=3)), [(BENCH, 80, 8)])
    missed = sig.missed_streak(trained, today)
    assert len(missed) == 1                              # day -2 only (day -1 skipped, day -3 done)
    assert "missed_streak" not in {s["key"] for s in trained.signals()[0]}


@pytest.mark.unit
def test_week_goal_only_when_behind_at_the_end_of_the_week(hc, monkeypatch):
    def goals(days_left, behind=True):
        return lambda: [{"progress": {"per": "week", "behind": behind, "days_left": days_left, "done": 1, "times": 3,
                                      "remaining": 2, "label": "Allenamento 3 volte a settimana", "hint": "1/3"}}]
    monkeypatch.setattr(hc, "goals", goals(2))
    s = {x["key"]: x for x in hc.signals()[0]}
    assert s["week_goal"]["kind"] == "goal" and s["week_goal"]["severity"] == "attenzione"
    monkeypatch.setattr(hc, "goals", goals(4))
    assert "week_goal" not in {x["key"] for x in hc.signals()[0]}
    monkeypatch.setattr(hc, "goals", goals(1, behind=False))
    assert "week_goal" not in {x["key"] for x in hc.signals()[0]}


@pytest.mark.unit
def test_weekly_metrics_twelve_weeks(trained):
    _, metrics = trained.signals()
    by_name: dict[str, dict] = {}
    for m in metrics:
        by_name.setdefault(m["name"], {})[m["week"]] = m
    assert len(by_name["fitness.sessions"]) == 12 and len(by_name["fitness.volume"]) == 12
    weeks = sorted(by_name["fitness.sessions"])
    assert by_name["fitness.sessions"][weeks[-1]]["value"] == 1            # today's squat
    assert by_name["fitness.volume"][weeks[-1]]["value"] == 550
    assert by_name["fitness.sessions"][weeks[0]]["label"] == "Allenamenti"
    # energy only for weeks with check-ins
    assert set(by_name["fitness.energy"]) <= set(weeks) and len(by_name["fitness.energy"]) in (1, 2)
    assert by_name["fitness.energy"][max(by_name["fitness.energy"])]["label"] == "Energia media"


@pytest.mark.unit
def test_signal_detail_topics(trained):
    stall = trained.signal_detail(f"stall:{BENCH}")
    assert stall.startswith("Allenamento") and "80×8" in stall and stall.count(";") == 3     # last 4 exposures
    assert trained.signal_detail("missed_streak").count(", ") == 5                  # 6 days in a row
    assert "energia 1" in trained.signal_detail("deload")
    assert "110" in trained.signal_detail(f"pr:{SQUAT}")
    assert trained.signal_detail("nonsense") is None
    assert trained.signal_detail("stall:unknown_exercise") is None


# ── API ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(trained, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    monkeypatch.setattr(main, "hercules", trained)
    monkeypatch.setattr(main.signals, "_evaluate", trained.signals)
    calls = []

    def fake_call(method, path, *, body=None, query=None, timeout=10):
        calls.append({"method": method, "path": path, "body": body, "query": query})
        return {"rows": []} if method == "GET" else {"applied": []}

    monkeypatch.setattr(main.signals, "_call", fake_call)
    monkeypatch.setattr(main.signals, "changed", lambda: calls.append({"method": "changed"}))
    return TestClient(main.app), calls, main


@pytest.mark.api
def test_signals_run_endpoint_syncs(api):
    client, calls, _ = api
    r = client.post("/api/hercules/signals/run")
    assert r.status_code == 200
    out = r.json()
    assert out["signals"] >= 4 and out["metrics"] >= 24 and out["written"] == out["signals"] + out["metrics"]
    put = next(c for c in calls if c["method"] == "PUT")
    ids = {row["id"] for row in put["body"]["rows"]}
    assert f"hercules:stall:{BENCH}" in ids and "hercules:deload" in ids


@pytest.mark.api
def test_module_context_topic(api):
    client, _, _ = api
    normal = client.get("/api/module/context").json()
    assert normal["module"] == "hercules" and normal["domain"] == "fitness" and normal["text"].startswith("Allenamento:")
    detail = client.get("/api/module/context", params={"topic": f"stall:{BENCH}", "budget": 600}).json()
    assert set(detail) == {"module", "domain", "updated_at", "text"} and "80×8" in detail["text"]
    short = client.get("/api/module/context", params={"topic": f"stall:{BENCH}", "budget": 60}).json()
    assert len(short["text"]) <= 60
    unknown = client.get("/api/module/context", params={"topic": "nope"}).json()
    assert unknown["text"].startswith("Allenamento:")


@pytest.mark.api
def test_writes_ask_for_reevaluation_and_agenda_rule(api):
    client, calls, main = api
    client.post("/api/hercules/checkin", json={"energy": 3})
    assert {"method": "changed"} in calls
    rules = {r.get("key") or r.get("id") or r.get("name"): r for r in main._agenda_rules()}
    assert any("hercules.signals" in str(k) for k in rules)

"""Reflection signals (docs/work/2026-10-20-riflessione-a-livelli): signals, weekly metrics, context topic and the
agenda endpoint, over the fake Archive store of ``test_hygieia``. No network: the signals transport is mocked.

Markers: unit, api
"""
from datetime import timedelta

import pytest

from hestia_common.signals_client import last_weeks, week_start

from app.core import signals as sig
from app.core.service import Hygieia
from app.core.store import Store

from .test_hygieia import SETTINGS, FakeArchive


@pytest.fixture
def hy():
    return Hygieia(Store(FakeArchive(), min_refresh_seconds=0), SETTINGS.get, tz_name="Europe/Rome")


@pytest.fixture
def cared(hy):
    """A daily routine done every day for 11 weeks and never this week (adherence drop), a weekly one done in each of
    the last 4 weeks (streak 4), a 7-per-week one never done (goal behind), journal scores in two weeks."""
    today = hy.today()
    weeks = last_weeks(12, today)
    daily = hy.save_routine({"name": "Viso sera", "cadence": {"mode": "daily"}, "steps": [{"label": "Detergente"}]})
    d = week_start(weeks[0])
    while d < week_start(weeks[-1]):
        hy.log_routine(daily["id"], d.isoformat())
        d += timedelta(days=1)
    weekly = hy.save_routine({"name": "Maschera capelli", "cadence": {"mode": "target", "times": 1, "per": "week"},
                              "steps": [{"label": "Maschera"}]})
    for k in range(1, 5):
        hy.log_routine(weekly["id"], (today - timedelta(days=7 * k)).isoformat())
    many = hy.save_routine({"name": "Massaggio", "cadence": {"mode": "target", "times": 7, "per": "week"},
                            "steps": [{"label": "Olio"}]})
    hy.journal_add({"date": (today - timedelta(days=7)).isoformat(), "area": "viso", "scores": {"brufoli": 4}})
    hy.journal_add({"date": (today - timedelta(days=7)).isoformat(), "area": "viso", "scores": {"brufoli": 2}})
    hy.journal_add({"date": (today - timedelta(days=21)).isoformat(), "area": "viso", "scores": {"brufoli": 5}})
    hy._ids = {"daily": daily["id"], "weekly": weekly["id"], "many": many["id"]}
    return hy


@pytest.mark.unit
def test_signals_keys_on_fake_data(cared):
    signals, _ = cared.signals()
    by_key = {s["key"]: s for s in signals}
    drop = by_key["adherence_drop"]
    assert drop["kind"] == "trend" and drop["severity"] == "attenzione" and drop["page"] == "statistiche"
    assert drop["metrics"]["previous"] - drop["metrics"]["percent"] >= 20
    goal = by_key[f"goal:{cared._ids['many']}"]
    assert goal["kind"] == "goal" and goal["page"] == f"routine/{cared._ids['many']}"
    streak = by_key[f"streak:{cared._ids['weekly']}"]
    assert streak["kind"] == "milestone" and streak["metrics"]["streak"] == 4
    for s in signals:
        assert "hygieia" not in s["text"].lower() and s["text"]


@pytest.mark.unit
def test_no_data_no_signals(hy):
    assert hy.signals() == ([], [])


@pytest.mark.unit
def test_weekly_metrics_twelve_weeks_and_journal(cared):
    _, metrics = cared.signals()
    adherence = {m["week"]: m for m in metrics if m["name"] == "selfcare.adherence"}
    weeks = last_weeks(12, cared.today())
    assert sorted(adherence) == weeks
    assert adherence[weeks[0]]["value"] == 100 and adherence[weeks[0]]["label"] == "Routine rispettate %"
    journal = [m for m in metrics if m["name"] == "selfcare.journal.viso.brufoli"]
    assert len(journal) == 2                                          # only weeks with entries
    assert {m["value"] for m in journal} == {3.0, 5.0} and journal[0]["label"] == "Diario Viso · Brufoli"


@pytest.mark.unit
def test_no_drop_when_the_week_goes_as_before(cared):
    today = cared.today()
    d = week_start(last_weeks(1, today)[0])
    while d <= today:
        cared.log_routine(cared._ids["daily"], d.isoformat())
        d += timedelta(days=1)
    cared.save_routine({"status": "paused"}, id=cared._ids["many"])
    assert "adherence_drop" not in {s["key"] for s in cared.signals()[0]}


@pytest.mark.unit
def test_signal_detail_topics(cared):
    text = cared.signal_detail("adherence_drop")
    assert text.startswith("Cura di sé") and "Viso sera" in text and "indietro" in text
    g = cared.signal_detail(f"goal:{cared._ids['many']}")
    assert "Massaggio" in g and "0/7" in g
    assert "serie 4" in cared.signal_detail(f"streak:{cared._ids['weekly']}")
    assert cared.signal_detail("nonsense") is None and cared.signal_detail("goal:missing") is None
    assert cared.context_text(400, "nonsense").startswith("Self care:")
    assert len(cared.context_text(60, "adherence_drop")) <= 60


# ── API ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(cared, monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as main
    monkeypatch.setattr(main, "hygieia", cared)
    monkeypatch.setattr(main.signals, "_evaluate", cared.signals)
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
    r = client.post("/api/selfcare/signals/run")
    assert r.status_code == 200
    out = r.json()
    assert out["signals"] >= 3 and out["metrics"] >= 14 and out["written"] == out["signals"] + out["metrics"]
    put = next(c for c in calls if c["method"] == "PUT")
    assert "hygieia:adherence_drop" in {row["id"] for row in put["body"]["rows"]}


@pytest.mark.api
def test_module_context_topic(api):
    client, _, _ = api
    normal = client.get("/api/module/context").json()
    assert normal["module"] == "hygieia" and normal["domain"] == "selfcare" and normal["text"].startswith("Self care:")
    detail = client.get("/api/module/context", params={"topic": "adherence_drop", "budget": 600}).json()
    assert set(detail) == {"module", "domain", "updated_at", "text"} and detail["text"].startswith("Cura di sé")
    unknown = client.get("/api/module/context", params={"topic": "nope"}).json()
    assert unknown["text"].startswith("Self care:")


@pytest.mark.api
def test_writes_ask_for_reevaluation_and_agenda_rule(api, cared):
    client, calls, main = api
    client.post(f"/api/selfcare/routines/{cared._ids['weekly']}/done", json={})
    assert {"method": "changed"} in calls
    assert "hygieia.signals" in str(main._agenda_rules())

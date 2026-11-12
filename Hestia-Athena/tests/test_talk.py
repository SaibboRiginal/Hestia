"""«Parla con te»: when she may write first, the reasons, Oracle writes, Hermes delivers, nothing repeated.
SPEC docs/work/2026-11-12-identita-e-proattivita. Markers: unit, api."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core import athena_settings as S
from core.athena_settings import settings
from core.reflection import local_day
from core.talk import KIND, Talk

pytestmark = pytest.mark.unit
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def _talk(monkeypatch, *, idle=7200, per_day=2, gap=4, sent=None, routes=None):
    monkeypatch.setitem(settings._effective, S.TALK_MAX_PER_DAY, per_day)
    monkeypatch.setitem(settings._effective, S.TALK_MIN_GAP_HOURS, gap)
    talk = Talk("http://hub/api", idle_seconds=lambda: idle, rng=random.Random(1))
    talk.reader = MagicMock()
    talk.reader.rows.return_value = [{"data": r, "at": r["at"]} for r in (sent or [])]
    talk.reader.signals.return_value = [
        {"severity": "alta", "domain": "fitness", "text": "Nessun allenamento da 9 giorni"},
        {"severity": "info", "domain": "finance", "text": "Spese nella norma"}]
    calls = []

    def route(service, method, path, *, query=None, body=None, timeout=10):
        calls.append((service, path, body))
        return (routes or {}).get(service, (200, {}))
    talk._route = route
    return talk, calls


def test_zero_per_day_never_writes(monkeypatch):
    talk, _ = _talk(monkeypatch, per_day=0)
    assert talk.due(NOW) is False


def test_first_message_waits_a_little_then_is_due(monkeypatch):
    talk, _ = _talk(monkeypatch)
    assert talk.due(NOW) is False                                   # never the first minute
    assert talk.due(NOW + timedelta(minutes=80)) is True


def test_daily_limit_and_pause_between_two_messages(monkeypatch):
    earlier = (NOW - timedelta(hours=1)).isoformat()
    talk, _ = _talk(monkeypatch, sent=[{"day": local_day(NOW), "text": "Hai mangiato?", "at": earlier}])
    assert talk.due(NOW + timedelta(hours=2)) is False              # pause of 4 hours from the last one
    assert talk.due(NOW + timedelta(hours=4)) is True
    talk, _ = _talk(monkeypatch, per_day=1, sent=[{"day": local_day(NOW), "text": "x", "at": earlier}])
    assert talk.due(NOW + timedelta(hours=8)) is False              # one a day, already written


def test_sends_what_oracle_wrote_through_hermes_and_keeps_it(monkeypatch):
    talk, calls = _talk(monkeypatch, routes={
        "psyche": (200, {"summary": {"mood_word": "giù", "energy": 2, "causes": ["lavoro"]}}),
        "oracle": (200, {"text": "Giornata pesante al lavoro?"})})
    out = talk.run("t1")
    assert out["status"] == "sent" and out["text"] == "Giornata pesante al lavoro?"
    by = {c[0]: c for c in calls}
    assert by["oracle"][1] == "api/chat/opener"
    assert by["oracle"][2]["reasons"] == ["Come si sente oggi: giù, energia 2/5 (per lavoro)",
                                          "Allenamento: Nessun allenamento da 9 giorni"]
    event = by["hermes"][2]
    assert event["event_type"] == "service.action_required" and event["payload"]["kind"] == KIND
    assert event["payload"]["_message"] == "Giornata pesante al lavoro?" and event["payload"]["_title"] == ""
    assert not event["payload"].get("_actions")
    assert by["archive"][2]["rows"][0]["kind"] == "talk"
    assert talk.due(datetime.now(timezone.utc) + timedelta(hours=1)) is False        # the pause started


def test_nothing_to_say_sends_nothing(monkeypatch):
    talk, calls = _talk(monkeypatch, routes={"oracle": (200, {"text": "", "skip": "nothing_to_say"})})
    assert talk.run("t2")["status"] == "nothing"
    assert not any(c[0] == "hermes" for c in calls)


def test_does_not_cut_in_while_he_is_chatting_unless_asked(monkeypatch):
    talk, calls = _talk(monkeypatch, idle=60, routes={"oracle": (200, {"text": "Ehi."})})
    assert talk.run("t3") == {"status": "chatting"} and calls == []
    assert talk.run("t4", force=True)["status"] == "sent"


def test_model_down_or_delivery_failed_retries_later(monkeypatch):
    talk, calls = _talk(monkeypatch, routes={"oracle": (503, {"detail": "no model"})})
    assert talk.run("t5")["status"] == "failed" and not any(c[0] == "hermes" for c in calls)
    talk, calls = _talk(monkeypatch, routes={"oracle": (200, {"text": "Ehi."}), "hermes": (500, {})})
    assert talk.run("t6")["status"] == "failed" and not any(c[0] == "archive" for c in calls)


def test_what_she_wrote_goes_to_oracle_as_avoid(monkeypatch):
    earlier = (NOW - timedelta(days=1)).isoformat()
    talk, calls = _talk(monkeypatch, sent=[{"day": "2026-11-11", "text": "Hai mangiato?", "at": earlier}],
                        routes={"oracle": (200, {"text": "Ehi."})})
    talk.due(NOW)
    talk.run("t7")
    assert next(c for c in calls if c[0] == "oracle")[2]["avoid"] == ["Hai mangiato?"]


def test_long_silence_is_a_reason(monkeypatch):
    talk, _ = _talk(monkeypatch)
    assert "Non vi sentite da circa 30 ore" in talk.reasons(30 * 3600)


@pytest.mark.api
def test_write_now_and_history_endpoints():
    import os
    import sys
    from fastapi.testclient import TestClient
    svc_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if svc_dir not in sys.path:
        sys.path.insert(0, svc_dir)
    with patch("requests.post"), patch("requests.get"), patch("requests.Session"):
        import app.main as main
    http = TestClient(main.app)
    with patch.object(main.runtime, "talk_now", return_value={"status": "started", "track": "parla"}) as now:
        assert http.post("/api/athena/think", params={"track": "parla"}).json()["track"] == "parla"
        now.assert_called_once()
    with patch.object(main.runtime.talk, "recent", return_value=[{"id": "1", "text": "Ehi.", "reasons": [], "x": 1}]):
        assert http.get("/api/athena/talk").json() == {"items": [
            {"id": "1", "day": None, "at": None, "text": "Ehi.", "reasons": [], "trigger": None}]}

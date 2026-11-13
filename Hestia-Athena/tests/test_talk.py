"""«Parla con te»: when she may write first, the reasons, Oracle writes, Hermes delivers, nothing repeated.
SPEC docs/work/2026-11-12-identita-e-proattivita. Markers: unit, api."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from core import athena_settings as S
from core.athena_settings import settings
from core.reflection import local_day
from core.talk import BARS, KIND, Talk, drive

pytestmark = pytest.mark.unit
NOW = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def _talk(monkeypatch, *, idle=30 * 3600, per_day=2, gap=4, sent=None, routes=None, eagerness=3, known=30):
    monkeypatch.setitem(settings._effective, S.TALK_MAX_PER_DAY, per_day)
    monkeypatch.setitem(settings._effective, S.TALK_MIN_GAP_HOURS, gap)
    monkeypatch.setitem(settings._effective, S.TALK_EAGERNESS, eagerness)
    talk = Talk("http://hub/api", idle_seconds=lambda: idle, known_days=lambda: known)
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


def test_no_clock_and_no_dice_the_drive_decides(monkeypatch):
    talk, _ = _talk(monkeypatch)
    assert talk.due(NOW) is True                                    # weighed at once: the drive says yes or no
    quiet, calls = _talk(monkeypatch, idle=3 * 3600)                # they talked 3 hours ago, one thing to say
    assert quiet.run("q1")["status"] == "quiet"
    assert not any(c[0] in ("oracle", "hermes") for c in calls)
    assert quiet.due(datetime.now(timezone.utc) + timedelta(minutes=10)) is False     # weighed again later
    assert quiet.due(datetime.now(timezone.utc) + timedelta(minutes=31)) is True


def test_drive_grows_with_silence_and_material_drops_when_ignored_low_when_new():
    base = dict(idle=24 * 3600, material=1, unanswered=0, answered_last=False, known_days=30)
    assert drive(**base) == drive(**base)                                            # same state, same answer
    assert drive(**{**base, "idle": 40 * 3600}) > drive(**base) > drive(**{**base, "idle": 2 * 3600})
    assert drive(**{**base, "material": 2}) > drive(**base) > drive(**{**base, "material": 0})
    assert drive(**{**base, "unanswered": 1}) < drive(**base) < drive(**{**base, "answered_last": True})
    assert drive(**{**base, "unanswered": 3}) == 0.0
    assert drive(**{**base, "known_days": 0}) == pytest.approx(drive(**base) / 2, abs=0.002)
    # First day: even with everything to say she stays under the default bar.
    assert drive(idle=None, material=3, unanswered=0, answered_last=False, known_days=0) < BARS[3]
    assert drive(**base) >= BARS[3] > drive(**{**base, "idle": 12 * 3600})


def test_eagerness_moves_the_bar(monkeypatch):
    shy, _ = _talk(monkeypatch, idle=20 * 3600, eagerness=1)
    assert shy.weigh(NOW)["wants"] is False
    chatty, _ = _talk(monkeypatch, idle=20 * 3600, eagerness=5)
    assert chatty.weigh(NOW)["wants"] is True


def test_remembers_the_last_days_and_whether_he_answered(monkeypatch):
    sent = [{"id": "b", "day": "2026-11-11", "text": "Com'è andata dal medico?", "answered": None,
             "at": (NOW - timedelta(hours=20)).isoformat()},
            {"id": "a", "day": "2026-11-10", "text": "Hai mangiato?", "answered": True,
             "at": (NOW - timedelta(days=2)).isoformat()}]
    history = {"days": [{"date": "2026-11-10", "mood_word": "bene"},
                        {"date": "2026-11-11", "mood_word": "giù", "stress": 4, "causes": ["lavoro"]},
                        {"date": local_day(NOW), "mood_word": "così così"}]}
    talk, calls = _talk(monkeypatch, sent=sent, idle=30 * 3600, routes={"psyche": (200, history)})
    state = talk.weigh(NOW)
    assert state["unanswered"] == 1                                 # 20 hours and he never wrote after it
    assert "2026-11-11: they felt giù, stress 4/5 (because of lavoro)" in state["past"]
    assert "2026-11-11: you wrote «Com'è andata dal medico?» (no answer)" in state["past"]
    assert "2026-11-10: you wrote «Hai mangiato?» (they answered)" in state["past"]
    assert any("do not insist" in line for line in state["past"])
    assert not any(local_day(NOW) in line and "felt" in line for line in state["past"])   # today is a reason
    stored = next(c for c in calls if c[0] == "archive")[2]["rows"][0]
    assert stored["id"] == "athena:talk:b" and stored["data"]["answered"] is False
    # He wrote 2 hours ago, after her message: answered.
    talk, _ = _talk(monkeypatch, sent=[dict(sent[0])], idle=2 * 3600)
    assert talk.weigh(NOW)["unanswered"] == 0 and talk._sent[0]["answered"] is True


def test_the_last_days_go_to_oracle(monkeypatch):
    talk, calls = _talk(monkeypatch, routes={"oracle": (200, {"text": "Ehi."}),
                                             "psyche": (200, {"days": [{"date": "2026-11-01", "mood_word": "bene"}],
                                                              "summary": {"mood_word": "giù"}})})
    assert talk.run("p1")["status"] == "sent"
    body = next(c for c in calls if c[0] == "oracle")[2]
    assert body["past"] == ["2026-11-01: they felt bene"]
    assert next(c for c in calls if c[0] == "archive")[2]["rows"][0]["data"]["drive"] > 0


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
    assert by["oracle"][2]["reasons"] == ["How they feel today: giù, energy 2/5 (because of lavoro)",
                                          "Allenamento: Nessun allenamento da 9 giorni",
                                          "You two have not talked for about 30 hours"]
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
    assert talk.silence_line(30 * 3600) == "You two have not talked for about 30 hours"
    assert talk.silence_line(3 * 3600) == "" and talk.silence_line(None) == ""


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
    row = {"id": "1", "text": "Ehi.", "reasons": ["How they feel today: giù, energy 2/5 (because of lavoro)"], "x": 1}
    state = {"drive": 0.4, "bar": 0.5, "wants": False, "past": ["hidden"],
             "reasons": ["You two have not talked for about 30 hours"]}
    with patch.object(main.runtime.talk, "recent", return_value=[row]), \
            patch.object(main.runtime.talk, "weigh", return_value=state):
        out = http.get("/api/athena/talk").json()
    assert out["items"] == [{"id": "1", "day": None, "at": None, "text": "Ehi.", "trigger": None, "drive": None,
                             "answered": None, "reasons": ["Come ti senti oggi: giù, energia 2/5 (per lavoro)"]}]
    assert out["state"]["reasons"] == ["Non vi sentite da circa 30 ore"] and "past" not in out["state"]
    assert out["state"]["drive"] == 0.4 and out["state"]["wants"] is False
    with patch.object(main.runtime.evidence, "known_days", return_value=2), \
            patch.object(main.runtime.evidence, "list", return_value=[{"key": "setting:x", "days": ["2026-11-12"]}]):
        out = http.get("/api/athena/evidence").json()
        assert out["known_days"] == 2 and out["min_days"] == 5 and out["seen_days"] == 3
        assert out["items"][0]["key"] == "setting:x"

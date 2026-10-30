"""Psyche («Umore»): check-ins, chat capture merge/undo, summaries, insights, signals, recap, endpoints. Markers: unit"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, NotFound, Store

from app.core.service import Psyche

pytestmark = pytest.mark.unit


def _settings(values=None):
    values = values or {}
    return lambda k, d=None: values.get(k, d)


@pytest.fixture
def ps():
    hub = FakeArchive()
    return Psyche(Store(hub, "mood-store", min_refresh_seconds=0), _settings()), hub


def _day(p, n):
    return (p.today() - timedelta(days=n)).isoformat()


def test_log_validates_and_keeps_only_the_vocabulary(ps):
    p, _ = ps
    r = p.log({"mood": "2", "energy": 1, "labels": ["Stanco", "giu", "boh"], "causes": "lavoro, sonno, x",
               "source": "tap"})
    assert r["mood"] == 2 and r["energy"] == 1 and r["labels"] == ["stanco", "giù"]
    assert r["causes"] == ["lavoro", "sonno"] and r["source"] == "tap" and r["mood_word"] == "giù"
    assert r["date"] == p.today().isoformat()
    for bad in ({"mood": 0}, {"mood": 6}, {}, {"mood": "molto"}, {"mood": 3, "date": "2999-01-01"}):
        with pytest.raises(Invalid):
            p.log(bad)
    assert p.log({"mood": 4, "date": "ieri"})["date"] == _day(p, 1)


def test_update_delete_and_not_found(ps):
    p, _ = ps
    r = p.log({"mood": 3})
    assert p.update(r["id"], {"mood": 5, "note": "cena con amici"})["mood"] == 5
    assert p.find(r["id"])["note"] == "cena con amici"
    assert p.delete(r["id"])["deleted"]
    with pytest.raises(NotFound):
        p.find(r["id"])


def test_chat_capture_merges_close_ones_and_undo_removes_the_last(ps):
    p, _ = ps
    a = p.capture({"mood": 2, "energy": 1, "labels": ["stanco"], "quote": "oggi sono stanco morto"})
    assert not a["merged"] and a["source"] == "chat"
    b = p.capture({"mood": 3, "labels": ["nervoso"], "quote": "e pure nervoso"})
    assert b["merged"] and b["id"] == a["id"] and b["labels"] == ["stanco", "nervoso"]
    assert b["energy"] == 1 and "stanco morto" in b["quote"] and "nervoso" in b["quote"]
    assert len(p.entries()) == 1
    p.log({"mood": 4, "source": "tap"})                  # a tap is never undone by «non segnarlo»
    out = p.undo_capture()
    assert out["deleted"] and out["id"] == a["id"]
    assert [r["source"] for r in p.entries()] == ["tap"]
    assert p.undo_capture() == {"deleted": False}


def test_capture_without_merge_window_adds(ps):
    hub = FakeArchive()
    p = Psyche(Store(hub, "mood-store", min_refresh_seconds=0), _settings({"psyche.capture.merge_minutes": 0}))
    p.capture({"mood": 2, "quote": "stanco"})
    p.capture({"mood": 4, "quote": "ora meglio"})
    assert len(p.entries()) == 2


def test_day_summary_last_wins(ps):
    p, _ = ps
    p.log({"mood": 2, "labels": ["stanco"]})
    p.log({"mood": 4, "labels": ["contento"], "energy": 3})
    s = p.today_view()["summary"]
    assert s["mood"] == 4 and s["min"] == 2 and s["max"] == 4 and s["labels"] == ["stanco", "contento"]
    assert s["count"] == 2 and s["energy"] == 3


def test_insights_need_enough_days_then_speak_plainly(ps):
    p, _ = ps
    p.log({"mood": 3})
    out = p.insights()
    assert not out["enough"] and "Servono ancora 6 giorni" in out["sentences"][0]
    for n in range(1, 12):
        p.log({"mood": 2 if n % 2 else 4, "date": _day(p, n), "labels": ["stanco"] if n % 2 else ["sereno"],
               "causes": ["lavoro"] if n % 2 else ["sport"]})
    out = p.insights()
    text = " ".join(out["sentences"])
    assert out["enough"] and "Ultimi 30 giorni" in text and "stanco" in text
    assert "«lavoro»" in text and "«sport»" in text
    assert "perché" not in text.lower()                  # never a cause


def test_signals_low_streak_energy_and_weekly_metrics(ps):
    p, _ = ps
    for n in range(0, 4):
        p.log({"mood": 1, "energy": 1, "date": _day(p, n)})
    sigs, mets = p.signals()
    keys = {s["key"] for s in sigs}
    assert {"low_streak", "energy_low"} <= keys
    assert {m["name"] for m in mets} == {"mood.avg", "mood.energy"}


def test_signals_drop_and_good_streak(ps):
    p, _ = ps
    for n in range(8, 20):
        p.log({"mood": 5, "date": _day(p, n)})
    for n in range(0, 5):
        p.log({"mood": 3, "date": _day(p, n)})
    keys = {s["key"] for s in p.signals()[0]}
    assert "mood_drop" in keys and "good_streak" not in keys
    hub = FakeArchive()
    q = Psyche(Store(hub, "mood-store", min_refresh_seconds=0), _settings())
    for n in range(0, 6):
        q.log({"mood": 5, "date": _day(q, n)})
    assert "good_streak" in {s["key"] for s in q.signals()[0]}


def test_recap_piece_and_checkin(ps):
    p, _ = ps
    today = p.today()
    r = p.recap(today, today + timedelta(days=1))
    assert r["done"] == [] and r["actions"] == [{"label": "Come stai?", "command": "mood_log"}]
    ask = p.checkin()
    assert ask["key"] == "psyche.checkin" and len(ask["actions"]) == 3
    assert all(a["service"] == "psyche" and a["path"] == "/api/mood" and a["resolves"] for a in ask["actions"])
    for n in range(0, 3):
        p.log({"mood": 2, "energy": 2, "labels": ["stanco"], "date": _day(p, n)})
    r = p.recap(today, today + timedelta(days=1))
    assert r["done"][0]["text"].startswith("Umore 2/5") and r["done"][0]["tone"] == "warning"
    assert r["next"] and not r["actions"] and p.checkin() is None


def test_context_text(ps):
    p, _ = ps
    assert "nessun dato" in p.context_text()
    p.log({"mood": 4, "labels": ["sereno"]})
    assert "4/5 (sereno)" in p.context_text()


def test_endpoints_capture_and_tools():
    from fastapi.testclient import TestClient
    from app import main
    hub = FakeArchive()
    main.psyche.store = Store(hub, "mood-store", min_refresh_seconds=0)
    main.signals.changed = lambda: None
    c = TestClient(main.app)
    out = c.post("/api/mood/capture", json={"mood": 2, "labels": ["stanco"], "quote": "sono stanco"}).json()
    assert out["source"] == "chat" and out["labels"] == ["stanco"]
    assert c.get("/api/mood/today").json()["summary"]["mood"] == 2
    assert c.post("/api/mood/capture/undo").json()["deleted"]
    assert c.post("/api/mood/tap", json={"mood": 4}).json()["source"] == "tap"
    logged = c.post("/api/mood/tools/log", json={"mood": "5", "labels": "contento"}).json()
    assert logged["saved"] and logged["undo"]["tool"] == "mood_delete"
    assert "display" in c.get("/api/mood/tools/history").json()
    assert c.post("/api/mood/tools/delete", json={"last": True}).json()["deleted"]
    assert c.post("/api/mood", json={"mood": 9}).status_code == 422
    assert c.get("/api/mood/options").json()["labels"][0] == "stanco"
    assert "Umore" in c.get("/api/module/context").json()["text"]
    assert c.post("/api/mood/checkin").json() == {"sent": False, "reason": "reminders_off"}
    piece = c.get("/api/module/recap").json()
    assert piece["module"] == "psyche"
    assert main.kit.registration()["capabilities"]["mood_capture_endpoint"] == "/api/mood/capture"

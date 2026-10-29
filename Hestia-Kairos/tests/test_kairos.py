"""Kairos (Scadenze): parsing, recurrence, calendar, mail proposals, daily notices, endpoints. Markers: unit, api"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, Store

from app.core.service import Deadlines, add_months, find_amount, find_due, guess_category

pytestmark = pytest.mark.unit


class FakeAgenda:
    def __init__(self):
        self.calls = []

    def show(self, key, title, start_at, **kw):
        self.calls.append(("show", key))

    def done(self, key):
        self.calls.append(("done", key))

    def cancel(self, key):
        self.calls.append(("cancel", key))


@pytest.fixture
def kd():
    hub, agenda = FakeArchive(), FakeAgenda()
    return Deadlines(Store(hub, "deadlines-store", min_refresh_seconds=0), lambda k, d=None: d, hub=hub,
                     agenda=agenda), hub, agenda


def test_helpers():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert guess_category("Polizza RCA auto") == "assicurazione"
    today = date(2026, 10, 1)
    assert find_due("La bolletta scade il 15/10/2026", today) == date(2026, 10, 15)
    assert find_due("Pagamento entro il 3 novembre 2026", today) == date(2026, 11, 3)
    assert find_due("Ci vediamo il 15/10/2026", today) is None          # no deadline words
    assert find_due("Scadenza 01/01/2020", today) is None               # past
    assert find_amount("Totale € 1.234,56") == 1234.56 and find_amount("importo 45,00 euro") == 45.0


def test_save_calendar_and_recurring_done(kd):
    deadlines, hub, agenda = kd
    due = (deadlines.today() + timedelta(days=10)).isoformat()
    d = deadlines.save({"title": "Bollo auto", "due": due, "recurrence": "yearly", "amount": 180})
    assert d["category"] == "bollo" and d["lead_days"] == 15 and ("show", f"kairos.{d['id']}") in agenda.calls
    rolled = deadlines.done(d["id"])
    assert rolled["status"] == "open" and rolled["due"] == add_months(date.fromisoformat(due), 12).isoformat()
    one = deadlines.save({"title": "Rinnovo passaporto", "due": due, "category": "documento"})
    assert deadlines.done(one["id"])["status"] == "done" and ("done", f"kairos.{one['id']}") in agenda.calls
    with pytest.raises(Invalid):
        deadlines.save({"title": "X", "due": "domani"})


def test_mail_proposal_confirm_and_dedupe(kd):
    deadlines, hub, agenda = kd
    when = deadlines.today() + timedelta(days=20)
    record = {"id": "m1", "payload": {"reference_id": "gm-1", "title": "La tua bolletta luce",
                                      "body": f"Importo 62,40 €, scadenza {when.strftime('%d/%m/%Y')}."}}
    out = deadlines.from_mail(record)
    assert out["status"] == "proposed" and ("hermes", "POST", f"kairos-proposal-{out['id']}") in hub.calls
    assert deadlines.from_mail(record)["status"] == "seen"
    assert not agenda.calls                                              # nothing in calendar before confirm
    d = deadlines.confirm(out["id"])
    assert d["status"] == "open" and d["amount"] == 62.4 and agenda.calls
    assert deadlines.from_mail({"id": "m2", "payload": {"title": "Newsletter", "body": "ciao"}})["status"] == "ignored"


def test_daily_notices_once_per_stage(kd):
    deadlines, hub, _ = kd
    d = deadlines.save({"title": "Tari", "due": (deadlines.today() + timedelta(days=3)).isoformat(), "category": "tassa"})
    assert deadlines.daily() == {"sent": 1}
    assert deadlines.daily() == {"sent": 0}
    deadlines.snooze(d["id"], 2)
    assert deadlines.list()[0]["snoozed_until"] > deadlines.today().isoformat()


def test_snooze_reminds_again_after_the_pause(kd):
    """Regression: «Fra 3 giorni» kept the stage marked as notified, so the reminder never came back."""
    deadlines, _, _ = kd
    real_today = deadlines.today()
    d = deadlines.save({"title": "Bollo", "due": (real_today + timedelta(days=10)).isoformat(), "category": "bollo"})
    assert deadlines.daily() == {"sent": 1}
    deadlines.snooze(d["id"], 3)
    assert deadlines.daily() == {"sent": 0}                      # still paused
    deadlines.today = lambda: real_today + timedelta(days=3)
    assert deadlines.daily() == {"sent": 1}                      # reminded again after the pause


@pytest.mark.api
def test_endpoints_and_tools(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub = FakeArchive()
    store = Store(hub, "deadlines-store", min_refresh_seconds=0)
    monkeypatch.setattr(main, "deadlines", Deadlines(store, lambda k, d=None: d, hub=hub, agenda=FakeAgenda()))
    monkeypatch.setattr(main.kit, "hub", hub)
    c = TestClient(main.app)
    due = (date.today() + timedelta(days=40)).isoformat()
    did = c.post("/api/deadlines", json={"title": "Assicurazione casa", "due": due}).json()["id"]
    assert c.get("/api/deadlines").json()["items"][0]["category"] == "assicurazione"
    assert c.post("/api/deadlines/tools/done", json={"deadline": did}).json()["status"] == "done"
    assert c.post("/api/deadlines/tools/consiglio", json={"deadline": "Assicurazione"}).status_code in (200, 404)
    assert c.get("/api/deadlines/categories").json()["recurrences"][0] == "none"
    reg = main.kit.registration()
    assert reg["capabilities"]["llm_usecases"][0]["id"] == "kairos.consiglio"

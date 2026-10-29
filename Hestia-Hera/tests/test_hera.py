"""Hera (Persone): cards, dates to the calendar, gift ideas, contacts, special moment, endpoints. Markers: unit, api"""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, NotFound, Store

from app.core.service import People, next_occurrence, parse_day

pytestmark = pytest.mark.unit


@pytest.fixture
def hp():
    hub = FakeArchive()
    return People(Store(hub, "people-store", min_refresh_seconds=0), lambda k, d=None: d, hub=hub), hub


def test_parse_day_forms():
    assert parse_day("14/02") == "02-14"
    assert parse_day("3/7/1990") == "1990-07-03"
    assert parse_day("1990-07-03") == "1990-07-03"
    with pytest.raises(Invalid):
        parse_day("31/02")
    assert next_occurrence("02-29", date(2027, 3, 1)) == date(2028, 2, 29)


def test_card_dates_go_to_calendar(hp):
    people, hub = hp
    p = people.save({"name": "Anna", "relation": "amico", "birthday": "14/02", "likes": "libri, tè"})
    assert p["likes"] == ["libri", "tè"] and p["dates"][0]["kind"] == "birthday"
    assert ("chronos", "POST", "api/special") in hub.calls
    people.gift_idea("anna", "Un romanzo di Calvino")
    people.gift_idea("Anna", "un romanzo di calvino")          # same idea once
    assert len(people.find("Anna")["gift_ideas"]) == 1
    with pytest.raises(NotFound):
        people.find("Luca")


def test_contact_due_and_daily_notice(hp):
    people, hub = hp
    p = people.save({"name": "Nonna", "relation": "famiglia", "contact_every_days": 7})
    people.contact(p["id"], when=(people.today() - timedelta(days=8)).isoformat())
    assert people.list()[0]["contact_due_in"] == -1
    assert people.daily()["due"] == 1 and ("hermes", "POST", f"hera-contact-{p['id']}") in hub.calls


def test_special_moment_sends_gift_ideas(hp):
    people, hub = hp
    p = people.save({"name": "Marta", "birthday": "01/01"})
    assert people.moment({"person_id": p["id"]})["ideas"] == 0
    people.gift_idea(p["id"], "Orecchini")
    assert people.moment({"person_id": p["id"]}) == {"handled": True, "ideas": 1}


@pytest.mark.api
def test_endpoints_and_tools(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub = FakeArchive()
    store = Store(hub, "people-store", min_refresh_seconds=0)
    monkeypatch.setattr(main, "people", People(store, lambda k, d=None: d, hub=hub))
    c = TestClient(main.app)
    pid = c.post("/api/people", json={"name": "Gio", "birthday": "05/05"}).json()["id"]
    assert c.get("/api/people").json()["items"][0]["name"] == "Gio"
    assert c.post("/api/people/tools/gift_idea", json={"person": "Gio", "idea": "Vinile"}).json()["saved"] is True
    assert c.get(f"/api/people/{pid}").json()["gift_ideas"][0]["text"] == "Vinile"
    reg = main.kit.registration()
    assert reg["capabilities"]["special_moment_endpoint"] == "/api/people/moment"
    assert reg["capabilities"]["recap_endpoint"]

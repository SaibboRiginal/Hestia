"""Demeter (Alimentazione): diet, meals, estimates, supplements, coach needs, endpoints. Markers: unit, api"""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.coach import validate_need
from hestia_common.module_kit import FakeArchive, Invalid, Store

from app.core.service import Nutrition, parse_estimate

pytestmark = pytest.mark.unit


class LlmHub(FakeArchive):
    answer = 'Ecco: {"kcal": 640, "protein": 32}'

    def llm(self, prompt, **kw):
        self.calls.append(("oracle", "POST", kw.get("use_case")))
        return self.answer


@pytest.fixture
def nf():
    hub, events = LlmHub(), []
    food = Nutrition(Store(hub, "food-store", min_refresh_seconds=0), lambda k, d=None: d, hub=hub,
                     on_event=lambda e, d: events.append(e))
    return food, hub, events


def test_parse_estimate():
    assert parse_estimate('{"kcal": 500.4, "protein": "20"}') == {"kcal": 500, "protein": 20}
    assert parse_estimate("non so") is None and parse_estimate('{"kcal": 0}') is None


def test_meals_diet_and_estimate(nf):
    food, hub, events = nf
    food.set_diet({"kcal": 2200, "protein": 140, "rules": "poco zucchero\nverdura a ogni pasto"})
    assert food.diet()["rules"] == ["poco zucchero", "verdura a ogni pasto"] and "changed" in events
    with pytest.raises(Invalid):
        food.set_diet({"kcal": 100})
    a = food.add_meal("Pasta al pomodoro", slot="pranzo")
    food.add_meal("Yogurt", slot="spuntino", kcal=120, protein=10)
    assert food.day_summary()["unknown"] == 1
    est = food.estimate(a["id"])
    assert est["kcal"] == 640 and est["estimated"] is True and ("oracle", "POST", "demeter.stima") in hub.calls
    assert food.update_meal(a["id"], {"kcal": 700})["estimated"] is False
    t = food.day_summary()
    assert t["kcal"] == 820 and t["kcal_target"] == 2200 and t["unknown"] == 0


def test_supplements_and_coach_needs(nf):
    food, hub, events = nf
    s = food.save_supplement({"name": "Creatina", "dose": "5 g", "time_of_day": "afternoon", "training_days_only": True})
    food.save_supplement({"name": "Vitamina D", "time_of_day": "morning", "days": [0, 3]})
    needs = food.needs(food.today(), food.today() + timedelta(days=7))["needs"]
    assert len(needs) == 2 and all(validate_need(n) for n in needs)
    crea = next(n for n in needs if n["id"] == f"supplement.{s['id']}")
    assert crea["with"] == {"tag": "workout", "relation": "same_day"}
    food.take("creatina")
    assert "done" in events and next(x for x in food.supplements_today() if x["name"] == "Creatina")["taken"]
    assert food.recap(food.today(), food.today() + timedelta(days=1)) is not None


@pytest.mark.api
def test_endpoints_and_tools(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub = LlmHub()
    monkeypatch.setattr(main, "food", Nutrition(Store(hub, "food-store", min_refresh_seconds=0),
                                                lambda k, d=None: d, hub=hub))
    monkeypatch.setattr(main, "_estimate_async", lambda meal: None)
    c = TestClient(main.app)
    assert c.post("/api/food/tools/pasto", json={"text": "Insalata", "kcal": 300}).json()["saved"] is True
    assert c.get("/api/food/today").json()["kcal"] == 300
    assert c.post("/api/food/tools/integratore", json={"name": "Omega 3"}).json()["name"] == "Omega 3"
    assert c.post("/api/food/tools/preso", json={"supplement": "omega"}).json()["taken"] is True
    assert c.get("/api/coach/needs").json()["needs"][0]["kind"] == "slot"
    assert "coach" in main.kit.registration()["tags"]

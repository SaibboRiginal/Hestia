"""Aphrodite (Aspetto): holidays, seasons, today's moment, per-client choice, pets and pictures. Markers: unit, api"""
import sys
from datetime import date
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, Store

from app.core.service import Appearance, easter, holiday, season

pytestmark = pytest.mark.unit


class ApolloHub(FakeArchive):
    def ok(self, service, method, path, **kw):
        if service == "apollo":
            self.calls.append((service, method, path, kw["body"]["ref"]))
            return {"id": f"job{len(self.calls)}", "status": "queued"}
        return super().ok(service, method, path, **kw)


@pytest.fixture
def ap():
    hub = ApolloHub()
    return Appearance(Store(hub, "appearance-store", min_refresh_seconds=0), hub), hub


def test_calendar_rules():
    assert easter(2027) == date(2027, 3, 28) and easter(2026) == date(2026, 4, 5)
    assert holiday(date(2026, 12, 31)) == "new_year" and holiday(date(2026, 12, 20)) == "christmas"
    assert holiday(date(2027, 1, 7)) is None and holiday(date(2026, 10, 31)) == "halloween"
    assert holiday(date(2026, 4, 6)) == "easter" and season(date(2026, 7, 1)) == "summer"
    assert season(date(2026, 12, 25)) == "winter"


def test_moment_wins_and_choice_off_is_standard(ap):
    look, _ = ap
    today = look.today()
    assert look.moment({"kind": "birthday", "person_id": "p1", "date": today.isoformat()})["handled"] is False
    look.moment({"key": "special.birthday.owner", "kind": "birthday", "title": "Il tuo compleanno",
                 "date": today.isoformat()})
    n = look.now("webui")
    assert n["profile"]["key"] == "birthday" and n["profile"]["effect"] == "confetti"
    look.set_choice("webui", auto=False)
    assert look.now("webui")["profile"]["key"] == "standard"


def test_custom_dated_profile_and_validation(ap):
    look, _ = ap
    p = look.save_profile({"name": "Vacanze", "effect": "sun", "when": {"from": "08-01", "to": "08-31"}})
    assert look.active(date(2026, 8, 15))[0] == p["id"]
    with pytest.raises(Invalid):
        look.save_profile({"name": "X", "effect": "fuochi"})


def test_pet_pictures_by_push(ap):
    look, hub = ap
    pet = look.save_pet({"name": "Miele", "species": "cat", "look": "orange tabby"})
    assert look.generate("pet", pet["id"])["asked"] == 3
    assert hub.calls[-1][3] == f"pet:{pet['id']}:sleep"
    look.image_done({"ref": f"pet:{pet['id']}:happy", "status": "done", "blob_ids": ["b9"]})
    look.set_choice("webui", pet=pet["id"])
    assert look.now()["pet"]["images"] == {"happy": "b9"}
    look.generate("profile", "christmas")
    look.image_done({"ref": "profile:christmas:background", "status": "done", "blob_ids": ["b10"]})
    assert look.profile("christmas")["background"] == "b10" and look.profile("christmas")["builtin"] is True


def test_drawn_mascot_by_default_and_can_be_turned_off(ap):
    """The mascot shows without any picture (dossier 2026-11-18-real-test-problems G)."""
    look, _ = ap
    assert look.now()["pet"]["drawn"] == "ember"                  # never chosen: the built-in mascot
    assert [p["id"] for p in look.pets()][:3] == ["builtin:ember", "builtin:cat", "builtin:owl"]
    look.set_choice("webui", pet="owl")
    assert look.now()["pet"]["id"] == "builtin:owl"
    look.set_choice("webui", pet="none")
    assert look.now()["pet"] is None
    with pytest.raises(Invalid):
        look.delete_pet("builtin:cat")
    pet = look.save_pet({"name": "Miele"})
    look.set_choice("webui", pet=pet["id"])
    look.delete_pet(pet["id"])
    assert look.now()["pet"]["drawn"] == "ember"                  # its pet deleted: the built-in one comes back


@pytest.mark.api
def test_endpoints_and_tools(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    hub = ApolloHub()
    monkeypatch.setattr(main, "look", Appearance(Store(hub, "appearance-store", min_refresh_seconds=0), hub))
    c = TestClient(main.app)
    assert c.get("/api/appearance/now").json()["profile"]["key"]
    assert c.post("/api/appearance/tools/choice", json={"auto": "false"}).json()["auto"] is False
    assert c.get("/api/appearance/now?client=webui").json()["profile"]["key"] == "standard"
    assert c.post("/api/appearance/tools/pet_create", json={"name": "Pip"}).json()["images_asked"] == 3
    assert main.kit.registration()["capabilities"]["special_moment_endpoint"] == "/api/appearance/moment"

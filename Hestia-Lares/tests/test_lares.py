"""Lares (Casa): mirror from Home Assistant, push changes, presence, commands, favourites, endpoints.
No network: a fake Home Assistant. Markers: unit, api"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from hestia_common.module_kit import FakeArchive, Invalid, NotFound, Store

from app.core.ha import HomeAssistant
from app.core.service import Home

pytestmark = pytest.mark.unit

STATES = [
    {"entity_id": "light.soggiorno", "state": "on", "attributes": {"friendly_name": "Luce soggiorno"}},
    {"entity_id": "light.cucina", "state": "off", "attributes": {"friendly_name": "Luce cucina"}},
    {"entity_id": "sensor.temp_sala", "state": "21.5", "attributes": {"friendly_name": "Sala",
                                                                       "unit_of_measurement": "°C",
                                                                       "device_class": "temperature"}},
    {"entity_id": "scene.cinema", "state": "scening", "attributes": {"friendly_name": "Cinema"}},
    {"entity_id": "person.me", "state": "home", "attributes": {"friendly_name": "Io"}},
    {"entity_id": "automation.x", "state": "on", "attributes": {}},
]


class FakeHA(HomeAssistant):
    def __init__(self):
        super().__init__("http://ha.local:8123", "t")
        self.calls = []

    def states(self):
        return STATES

    def call(self, domain, service, data):
        self.calls.append((domain, service, data))


class Presence:
    def __init__(self):
        self.signals = []

    def signal(self, key, value, **kw):
        self.signals.append((key, value))


@pytest.fixture
def lh():
    ha, pres = FakeHA(), Presence()
    settings = {"lares.persona": "person.me"}
    return Home(Store(FakeArchive(), "home-store", min_refresh_seconds=0), ha, lambda k, d=None: settings.get(k, d),
                presence=pres), ha, pres


def test_mirror_status_and_presence(lh):
    home, ha, pres = lh
    s = home.status()
    assert s["lights_on"] == ["Luce soggiorno"] and s["temperatures"] == ["Sala 21.5°C"] and s["person"] == "home"
    assert ("home.present", True) in pres.signals
    assert "automation.x" not in home.entities
    home.changed({"entity_id": "person.me", "state": "not_home", "attributes": {"friendly_name": "Io"}})
    assert pres.signals[-1] == ("home.present", False)
    assert ha.ws_url() == "ws://ha.local:8123/api/websocket"


def test_commands_and_favorites(lh):
    home, ha, _ = lh
    assert home.command("cucina", "on", 40)["ok"]
    assert ha.calls[-1] == ("light", "turn_on", {"entity_id": "light.cucina", "brightness_pct": 40})
    home.scene("cinema")
    assert ha.calls[-1] == ("scene", "turn_on", {"entity_id": "scene.cinema"})
    with pytest.raises(Invalid):
        home.command("luce", "on")                                    # two lights match
    with pytest.raises(NotFound):
        home.command("garage", "on")
    f = home.add_favorite("light.soggiorno", "Sera", "Sala")
    home.run_favorite(f["id"])
    assert ha.calls[-1][1] == "toggle" and home.favorites()[0]["label"] == "Sera"


def test_not_configured_says_so():
    home = Home(Store(FakeArchive(), "home-store"), HomeAssistant("", ""), lambda k, d=None: d)
    assert home.status() == {"configured": False, "connected": False}
    with pytest.raises(Invalid):
        home.list()


@pytest.mark.api
def test_endpoints_and_tools(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    ha = FakeHA()
    monkeypatch.setattr(main, "home", Home(Store(FakeArchive(), "home-store", min_refresh_seconds=0), ha,
                                           lambda k, d=None: d))
    c = TestClient(main.app)
    assert c.get("/api/home/status").json()["entities"] == 5
    assert c.post("/api/home/tools/comando", json={"device": "Luce cucina", "command": "on"}).json()["ok"] is True
    assert c.post("/api/home/entities/light.cucina/off").json()["ok"] is True
    assert c.get("/api/home/persons/options").json()["options"][1]["value"] == "person.me"
    assert c.post("/api/home/tools/comando", json={"device": "Luce cucina", "command": "boh"}).json().get("error")

"""Connected services as one list (Marko 2026-11-07: N services like a marketplace, the same card and the same way to
connect for all). No network: a fake Garmin client, Google callables recorded."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import connections
from providers.garmin import GarminService
from test_devices import FakeGarmin

pytestmark = pytest.mark.unit


class FakeGoogle:
    def __init__(self):
        self.s = {"client_set": False, "linked": False, "pending": False, "auth_url": "", "public_redirect": False,
                  "error": ""}
        self.calls = []

    def save(self, values):
        self.calls.append(("client", values.get("client_id")))
        self.s["client_set"] = True

    def initiate(self):
        self.s.update(pending=True, auth_url="https://accounts.google.com/o/oauth2/auth?x=1")
        return {"auth_url": self.s["auth_url"]}

    def complete(self, code):
        if code != "ok":
            raise connections.ConnectError("Google non ha accettato il codice.")
        self.s.update(pending=False, linked=True)

    def cancel(self):
        self.s["pending"] = False


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(connections, "_REGISTRY", {})
    g = FakeGoogle()
    connections.register(connections.GoogleConnector(state=lambda: dict(g.s), save_client=g.save, initiate=g.initiate,
                                                     complete=g.complete, cancel=g.cancel))
    svc = GarminService(tmp_path / "g", factory=lambda e=None, p=None: FakeGarmin(e, p, mfa=bool(e)), env=lambda k: None)
    synced = []
    connections.register(connections.GarminConnector(svc, sync=lambda: synced.append(1) or {"status": "ok"},
                                                     first_sync=lambda: synced.append("first")))
    connections.register(connections.PhoneConnector(lambda: {"configured": False}))
    app = FastAPI()
    app.include_router(connections.router)
    return {"c": TestClient(app), "g": g, "synced": synced}


def test_one_list_same_shape_and_setup_hides_the_phone(world):
    items = world["c"].get("/api/gateway/connections").json()["items"]
    assert [i["id"] for i in items] == ["google", "garmin", "phone"]
    for i in items:                                   # every service: the same fields, a step shown at once
        assert set(i) >= {"id", "label", "icon", "what", "state", "detail", "step", "actions"}
        assert i["state"] == "not_connected" and i["step"]["kind"] == "form"
    setup = world["c"].get("/api/gateway/connections", params={"place": "setup"}).json()["items"]
    assert [i["id"] for i in setup] == ["google", "garmin"]


def test_garmin_login_then_code_then_connected(world):
    c = world["c"]
    r = c.post("/api/gateway/connections/garmin", json={"values": {"email": "me@example.org", "password": "pw"}}).json()
    assert r["item"]["state"] == "waiting" and r["item"]["step"]["fields"][0]["name"] == "code"
    assert c.post("/api/gateway/connections/garmin", json={"values": {"code": "000000"}}).status_code == 422
    r = c.post("/api/gateway/connections/garmin", json={"values": {"code": "123456"}}).json()
    assert r["item"]["state"] == "connected" and world["synced"] == ["first"]
    assert [a["id"] for a in r["item"]["actions"]] == ["sync", "forget"]
    assert c.post("/api/gateway/connections/garmin/sync").json()["message"] == "Letto."
    assert c.delete("/api/gateway/connections/garmin").json()["item"]["state"] == "not_connected"


def test_google_client_then_page_then_pasted_code(world):
    c = world["c"]
    bad = c.post("/api/gateway/connections/google", json={"values": {}})
    assert bad.status_code == 422 and "ID client" in bad.json()["detail"]
    r = c.post("/api/gateway/connections/google", json={"values": {"client_id": "x.apps.googleusercontent.com",
                                                                    "client_secret": "s"}}).json()
    assert r["open_url"].startswith("https://accounts.google.com") and r["item"]["state"] == "waiting"
    assert r["item"]["step"]["kind"] == "wait" and r["item"]["step"]["fields"][0]["name"] == "code"
    wrong = c.post("/api/gateway/connections/google", json={"values": {"code": "no"}})
    assert wrong.status_code == 422 and "codice" in wrong.json()["detail"]
    r = c.post("/api/gateway/connections/google", json={"values": {"code": "ok"}}).json()
    assert r["item"]["state"] == "connected"
    assert c.post("/api/gateway/connections/nothing/sync").status_code == 404

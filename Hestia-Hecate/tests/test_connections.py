"""Connected services as one list (Marko 2026-11-07: N services like a marketplace; 2026-11-19: the same way for every
module, docs/work/2026-11-19-unified-connections). No network: a fake Garmin client, Google/Outlook callables recorded,
the key writer (Hephaestus through Hub) replaced by a dict."""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import connections
from hestia_common.connections import Connections
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
            raise connections.ConnectError("Google did not accept the code.")
        self.s.update(pending=False, linked=True)

    def cancel(self):
        self.s["pending"] = False


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def put(self, key, value, **kw):
        self.values[key] = value
        return True


@pytest.fixture()
def world(tmp_path, monkeypatch):
    hub = Connections("hecate", "/api/gateway/", env_file=tmp_path / ".env")
    saved = {}

    def save_secrets(values):
        for name, value in values.items():
            env = hub.key_env(name)
            saved[env] = value
            if value:
                monkeypatch.setenv(env, value)
            else:
                monkeypatch.delenv(env, raising=False)

    monkeypatch.setattr(hub, "save_secrets", save_secrets)

    def send(envs):          # clear_legacy: old hand-written lines emptied
        for env, value in envs.items():
            saved[env] = value
            monkeypatch.delenv(env, raising=False)

    monkeypatch.setattr(hub, "_send", send)
    monkeypatch.setattr(connections, "hub", hub)
    g = FakeGoogle()
    hub.register(connections.GoogleConnector(state=lambda: dict(g.s), save_client=g.save, initiate=g.initiate,
                                             complete=g.complete, cancel=g.cancel))
    svc = GarminService(tmp_path / "g", factory=lambda e=None, p=None: FakeGarmin(e, p, mfa=bool(e)), env=lambda k: None)
    synced = []
    hub.register(connections.GarminConnector(svc, sync=lambda: synced.append(1) or {"status": "ok"},
                                             first_sync=lambda: synced.append("first")))
    hub.register(connections.PhoneConnector(lambda: {"configured": bool(os.getenv("HECATE_KEY_PHONE")), "last": {}},
                                            connections=hub))
    app = FastAPI()
    app.include_router(hub.router())
    return {"c": TestClient(app), "g": g, "synced": synced, "hub": hub, "saved": saved, "app": app}


def test_one_list_same_shape_groups_and_setup_hides_the_phone(world):
    items = world["c"].get("/api/gateway/connections").json()["items"]
    assert [i["id"] for i in items] == ["google", "garmin", "phone"]
    assert [i["group"] for i in items] == ["account", "device", "device"]
    for i in items:                                   # every service: the same fields, a step shown at once, Test
        assert set(i) >= {"id", "label", "icon", "what", "group", "keywords", "state", "detail", "step", "actions", "test"}
        assert i["state"] == "not_connected" and i["step"]["kind"] == "form"
    setup = world["c"].get("/api/gateway/connections", params={"place": "setup"}).json()["items"]
    assert [i["id"] for i in setup] == ["google", "garmin"]
    assert [m["id"] for m in world["hub"].manifest()] == ["google", "garmin", "phone"]


def test_garmin_login_then_code_then_connected(world):
    c = world["c"]
    r = c.post("/api/gateway/connections/garmin", json={"values": {"email": "me@example.org", "password": "pw"}}).json()
    assert r["item"]["state"] == "waiting" and r["item"]["step"]["fields"][0]["name"] == "code"
    assert c.post("/api/gateway/connections/garmin", json={"values": {"code": "000000"}}).status_code == 422
    r = c.post("/api/gateway/connections/garmin", json={"values": {"code": "123456"}}).json()
    assert r["item"]["state"] == "connected" and world["synced"] == ["first"]
    assert [a["id"] for a in r["item"]["actions"]] == ["sync", "forget"]
    assert c.post("/api/gateway/connections/garmin/sync").json()["message"] == "Letto."
    test = c.post("/api/gateway/connections/garmin/test").json()["result"]
    assert test["ok"] is True and test["facts"] == []
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
    assert wrong.status_code == 422 and "code" in wrong.json()["detail"]
    r = c.post("/api/gateway/connections/google", json={"values": {"code": "ok"}}).json()
    assert r["item"]["state"] == "connected"
    assert c.post("/api/gateway/connections/nothing/sync").status_code == 404


def test_phone_key_is_created_here_shown_once_then_unlinked(world):
    c = world["c"]
    r = c.post("/api/gateway/connections/phone", json={"values": {}}).json()
    key = world["saved"]["HECATE_KEY_PHONE"]
    assert len(key) >= 24 and r["item"]["state"] == "waiting" and r["item"]["step"]["code"] == key
    r = c.post("/api/gateway/connections/phone/hide").json()
    assert r["item"]["state"] == "connected" and key not in str(r["item"])
    assert c.delete("/api/gateway/connections/phone").json()["item"]["state"] == "not_connected"
    assert world["saved"]["HECATE_KEY_PHONE"] == ""


def test_outlook_app_then_microsoft_code_then_connected(world, monkeypatch):
    for k in ("HECATE_KEY_OUTLOOK_CLIENT_ID", "HECATE_KEY_OUTLOOK_TENANT", "HECATE_KEY_OUTLOOK_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    polls = iter([{"status": "pending"}, {"status": "authorized"}])
    linked = {"on": False}

    def poll():
        out = next(polls)
        linked["on"] = out["status"] == "authorized"
        return out

    world["hub"].register(connections.OutlookConnector(
        linked=lambda: linked["on"], initiate=lambda: {"user_code": "ABCD-1234", "verification_url": "https://microsoft.com/devicelogin"},
        poll=poll, cancel=lambda: None, unlink=lambda: linked.update(on=False), connections=world["hub"]))
    c = world["c"]
    first = [i for i in c.get("/api/gateway/connections").json()["items"] if i["id"] == "outlook"][0]
    assert first["group"] == "account" and [f["name"] for f in first["step"]["fields"]] == ["client_id", "tenant", "client_secret"]
    assert c.post("/api/gateway/connections/outlook", json={"values": {"client_id": "x"}}).status_code == 422
    r = c.post("/api/gateway/connections/outlook", json={"values": {"client_id": "11111111-2222-3333-4444-555555555555"}}).json()
    assert world["saved"]["HECATE_KEY_OUTLOOK_TENANT"] == "common" and "HECATE_KEY_OUTLOOK_CLIENT_SECRET" not in world["saved"]
    assert r["open_url"] == "https://microsoft.com/devicelogin"
    assert r["item"]["state"] == "waiting" and r["item"]["step"]["code"] == "ABCD-1234"
    again = [i for i in c.get("/api/gateway/connections").json()["items"] if i["id"] == "outlook"][0]
    assert again["state"] == "connected"


def test_gmail_instant_notices_card_saves_settings_and_the_account(world, monkeypatch):
    monkeypatch.delenv("HECATE_KEY_GMAIL_PUBSUB_ACCOUNT", raising=False)
    settings, restarted = FakeSettings(), []
    status = {"configured": False}
    world["hub"].register(connections.GmailPushConnector(
        settings=settings, topic_key="hecate.gmail.push_topic", subscription_key="hecate.gmail.push_subscription",
        status=lambda: dict(status), restart=lambda: restarted.append(1), connections=world["hub"]))
    c = world["c"]
    url = "/api/gateway/connections/gmail_push"
    assert c.post(url, json={"values": {"topic": "x", "subscription": "y"}}).status_code == 422
    good = {"topic": "projects/p/topics/t", "subscription": "projects/p/subscriptions/s"}
    assert "JSON" in c.post(url, json={"values": good}).json()["detail"]
    assert c.post(url, json={"values": {**good, "account": '{"type": "user"}'}}).status_code == 422
    r = c.post(url, json={"values": {**good, "account": '{"type": "service_account", "private_key": "-----BEGIN KEY-----"}'}})
    assert r.status_code == 200 and restarted == [1]
    assert settings.values == {"hecate.gmail.push_topic": "projects/p/topics/t",
                               "hecate.gmail.push_subscription": "projects/p/subscriptions/s"}
    import base64
    import json
    raw = world["saved"]["HECATE_KEY_GMAIL_PUBSUB_ACCOUNT"]
    assert " " not in raw and json.loads(base64.b64decode(raw))["type"] == "service_account"
    status.update(configured=True, active=True)
    row = [i for i in c.get("/api/gateway/connections").json()["items"] if i["id"] == "gmail_push"][0]
    assert row["state"] == "connected" and row["in_setup"] is False
    c.delete(url)
    assert settings.values["hecate.gmail.push_topic"] == "" and world["saved"]["HECATE_KEY_GMAIL_PUBSUB_ACCOUNT"] == ""


class FakeMcpHTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=8):
        self.calls.append((url, (headers or {}).get("Authorization")))
        code = 401 if "locked" in url and headers.get("Authorization") != "Bearer ok" else 200
        return type("R", (), {"status_code": code})()


def test_external_mcp_servers_add_test_remove_and_adopt_old_env(world, monkeypatch):
    """2026-11-27: N external MCP servers on one card; old HECATE_MCP_<NAME>_URL/_KEY lines are moved in once."""
    st, http = FakeSettings(), FakeMcpHTTP()
    monkeypatch.setenv("HECATE_MCP_NOTION_URL", "https://mcp.notion.example/mcp")
    monkeypatch.setenv("HECATE_MCP_NOTION_KEY", "old-key")
    card = world["hub"].register(connections.ExternalMcpConnector(settings=st, connections=world["hub"], http=http))
    card.adopt()
    assert st.values["hecate.mcp.servers"] == [{"name": "notion", "url": "https://mcp.notion.example/mcp"}]
    assert world["saved"]["HECATE_KEY_MCP_NOTION"] == "old-key"
    assert world["saved"]["HECATE_MCP_NOTION_URL"] == "" and "HECATE_MCP_NOTION_URL" not in os.environ
    c = world["c"]
    assert c.post("/api/gateway/connections/external_mcp", json={"values": {"name": "my server", "url": "ftp://x"}}).status_code == 422
    out = c.post("/api/gateway/connections/external_mcp",
                 json={"values": {"name": "Locked", "url": "https://locked.example/mcp", "key": "ok"}}).json()
    assert out["item"]["state"] == "connected" and "locked" in out["item"]["detail"]
    assert world["saved"]["HECATE_KEY_MCP_LOCKED"] == "ok" and ("https://locked.example/mcp", "Bearer ok") in http.calls
    result = c.post("/api/gateway/connections/external_mcp/test").json()["result"]
    assert result["ok"] and len(result["facts"]) == 2
    ids = [a["id"] for a in out["item"]["actions"]]
    assert "remove-locked" in ids and "add" in ids
    c.post("/api/gateway/connections/external_mcp/remove-locked")
    assert [r["name"] for r in st.values["hecate.mcp.servers"]] == ["notion"] and world["saved"]["HECATE_KEY_MCP_LOCKED"] == ""
    listed = str(c.get("/api/gateway/connections").json())
    assert "old-key" not in listed and "Bearer" not in listed


def test_google_with_the_builtin_app_is_one_button_then_login(world):
    """The release brings Hestia's own Google app: no client form, one button, Google's page; «use your own» stays."""
    c, g = world["c"], world["g"]
    g.s.update(client_set=True, builtin=True)
    item = c.get("/api/gateway/connections").json()["items"][0]
    assert item["id"] == "google" and item["step"]["fields"] == [] and item["step"]["submit"]
    assert [a["id"] for a in item["actions"]] == ["client"] and item["actions"][0]["label"] in ("Use your own Google app", "Usa la tua app Google")
    r = c.post("/api/gateway/connections/google", json={"values": {}}).json()
    assert r["open_url"].startswith("https://accounts.google.com") and "Hestia" in r["item"]["step"]["text"]
    assert g.calls == []                               # nothing saved: the built-in client is used as it is

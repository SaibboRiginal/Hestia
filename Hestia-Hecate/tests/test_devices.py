"""Garmin (B10) and the phone as a sensor (Cindy 32), dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4.
No network: a fake Garmin client, the feed publisher and presence replaced by recorders."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import devices_api
from providers.garmin import GarminError, GarminService, normalise_activity, normalise_sleep

pytestmark = pytest.mark.unit

SLEEP = {"dailySleepDTO": {"sleepTimeSeconds": 26100, "deepSleepSeconds": 5400, "remSleepSeconds": 6000,
                           "sleepStartTimestampGMT": 1761696000000, "sleepEndTimestampGMT": 1761722100000,
                           "sleepScores": {"overall": {"value": 82}}}}
RUN = {"activityId": 991, "activityName": "Corsa mattutina", "activityType": {"typeKey": "running"},
       "startTimeLocal": "2026-10-29 07:10:00", "duration": 1830.0, "distance": 5120.0, "calories": 410,
       "averageHR": 151, "activityTrainingLoad": 88.4}


class FakeGarmin:
    def __init__(self, email=None, password=None, mfa=False):
        self.email, self.password, self.mfa = email, password, mfa
        self.garth = self

    def login(self, tokenstore=None):
        return ("needs_mfa", {"s": 1}) if self.mfa else (None, None)

    def resume_login(self, state, code):
        assert code == "123456"

    def dump(self, path):
        from pathlib import Path
        Path(path, "oauth1_token.json").write_text("{}")

    def get_sleep_data(self, d):
        return SLEEP

    def get_stats(self, d):
        return {"totalSteps": 9876, "restingHeartRate": 52, "bodyBatteryHighestValue": 91,
                "bodyBatteryLowestValue": 22, "bodyBatteryAtWakeTime": 77, "averageStressLevel": 31}

    def get_hrv_data(self, d):
        raise RuntimeError("no hrv on this watch")

    def get_training_readiness(self, d):
        return [{"score": 64}]

    def get_activities_by_date(self, a, b):
        return [RUN]


def test_normalisers():
    s = normalise_sleep(SLEEP)
    assert s["minutes"] == 435 and s["deep_minutes"] == 90 and s["score"] == 82 and s["end"].startswith("2025-10-29T07:15")
    a = normalise_activity(RUN)
    assert a == {"id": "991", "kind": "corsa", "type": "running", "name": "Corsa mattutina",
                 "start": "2026-10-29 07:10:00", "minutes": 30, "km": 5.12, "calories": 410, "avg_hr": 151,
                 "training_load": 88.4}
    assert normalise_sleep({}) is None


def test_login_with_code_then_day(tmp_path):
    svc = GarminService(tmp_path / "g", factory=lambda e=None, p=None: FakeGarmin(e, p, mfa=bool(e)), env=lambda k: None)
    assert svc.status()["connected"] is False
    assert svc.login("me@example.org", "pw")["status"] == "needs_code"
    assert svc.login_code("123456")["status"] == "connected"
    assert svc.status()["tokens"] is True
    day = svc.day(date(2026, 10, 29))
    assert day["steps"] == 9876 and day["readiness"] == 64 and day["body_battery"]["morning"] == 77
    assert "hrv" not in day                                     # a failing part is skipped, the day stays
    assert day["activities"][0]["kind"] == "corsa"
    svc.forget()
    with pytest.raises(GarminError):
        svc.client()


@pytest.fixture
def api(tmp_path, monkeypatch):
    svc = GarminService(tmp_path / "g", factory=lambda e=None, p=None: FakeGarmin(e, p), env=lambda k: None)
    monkeypatch.setattr(devices_api, "garmin", svc)
    sent = {"feeds": [], "signals": []}

    class Feeds:
        def publish(self, kind, item):
            sent["feeds"].append((kind, item))
            return {"delivered": ["x"], "failed": []}

    class Presence:
        def signal(self, key, value, **kw):
            sent["signals"].append((key, value))

    monkeypatch.setitem(devices_api._clients, "feeds", Feeds())
    monkeypatch.setitem(devices_api._clients, "presence", Presence())
    monkeypatch.setattr(devices_api.threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda s: target()})())
    app = FastAPI()
    app.include_router(devices_api.router)
    return TestClient(app), svc, sent


def test_sync_pushes_feed(api):
    client, svc, sent = api
    assert client.post("/api/gateway/garmin/sync", json={}).json()["status"] == "not_connected"
    svc.login("me@example.org", "pw")
    sent["feeds"].clear()
    out = client.post("/api/gateway/garmin/sync", json={"days": 2}).json()
    assert out["status"] == "ok" and len(out["days"]) == 2
    assert [k for k, _ in sent["feeds"]] == ["wearable.daily", "wearable.daily"]
    assert sent["signals"][-1][0] == "wearable.woke_at"


def test_login_endpoint_never_echoes_password(api):
    client, _, _ = api
    r = client.post(devices_api.LOGIN_PATH, json={"values": {"email": "me@example.org", "password": "secret-pw"}})
    assert r.status_code == 200 and "secret-pw" not in r.text


def test_phone_webhook(api, monkeypatch):
    client, _, sent = api
    assert client.post("/api/gateway/phone/push", json={"type": "state"}).status_code == 503
    monkeypatch.setenv("HECATE_PHONE_TOKEN", "tok")
    assert client.post("/api/gateway/phone/push", json={}, headers={"X-Hestia-Phone-Token": "no"}).status_code == 401
    monkeypatch.setattr(devices_api.hecate_settings, "get",
                        lambda k, d=None: {"hecate.telefono.wifi_casa": ["CasaNet"],
                                           "hecate.telefono.app": ["Banca"]}.get(k, d))
    h = {"X-Hestia-Phone-Token": "tok"}
    out = client.post("/api/gateway/phone/push", json={"type": "state", "wifi": "casanet", "charging": True},
                      headers=h).json()
    assert out["state"]["home"] is True and ("phone.home", True) in sent["signals"]
    assert client.post("/api/gateway/phone/push", json={"type": "notification", "app": "Chat", "text": "ciao"},
                       headers=h).json()["status"] == "ignored"
    client.post("/api/gateway/phone/push", json={"type": "notification", "app": "Banca", "title": "Pagamento",
                                                 "text": "12,50 € presso ESSELUNGA"}, headers=h)
    assert sent["feeds"][-1][0] == "phone.notification" and sent["feeds"][-1][1]["app"] == "Banca"


def test_feed_publisher_finds_subscribers_and_pushes():
    from hestia_common.feeds import FeedPublisher, capabilities

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Session:
        posts = []

        def get(self, url, timeout):
            return Resp({"services": [
                {"name": "hercules", "capabilities": capabilities({"wearable.daily": "/api/hercules/wearable"})},
                {"name": "hygieia", "status": "offline", "capabilities": {"feeds": {"wearable.daily": "/x"}}},
                {"name": "plutus", "capabilities": {"feeds": {"phone.notification": "/api/finance/phone"}}}]})

        def post(self, url, json, timeout):
            self.posts.append(url)
            return Resp({"status_code": 200})

    pub = FeedPublisher("http://hub/api", session=Session())
    assert pub.publish("wearable.daily", {"date": "2026-10-29"}) == {"delivered": ["hercules"], "failed": []}
    assert Session.posts == ["http://hub/api/route/hercules/api/hercules/wearable"]
    with pytest.raises(ValueError):
        capabilities({"nope": "/x"})


def test_away_state_needs_a_real_signal():
    """Regression: «false» was true with no phone at all → «Fuori casa» forever. Now «== False» per source."""
    from app.devices_api import PRESENCE_STATES
    groups = PRESENCE_STATES["away_from_home"]["when"]
    assert {g[0]["signal"] for g in groups} == {"phone.home", "home.present"}
    assert all(g[0]["op"] == "==" and g[0]["value"] is False for g in groups)


def test_feed_publisher_reads_the_registry_right_after_boot(monkeypatch):
    """Regression: the empty cache stamped 0.0 looked fresh while monotonic() < cache time (fresh host/CI runner)."""
    import hestia_common.feeds as feeds

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"services": [{"name": "hercules", "capabilities": feeds.capabilities({"wearable.daily": "/w"})}]}

    class Session:
        def get(self, url, timeout):
            return Resp()

    monkeypatch.setattr(feeds.time, "monotonic", lambda: 5.0)
    assert feeds.FeedPublisher("http://hub/api", session=Session()).subscribers("wearable.daily")

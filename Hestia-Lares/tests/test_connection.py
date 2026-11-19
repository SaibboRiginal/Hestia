"""«Home Assistant» card (docs/work/2026-11-19-unified-connections): «Test» answers with version, home name and
device count; a new address or token reconnects the push stream. No network: a fake HTTP session. Markers: unit"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from app.core.ha import HomeAssistant

pytestmark = pytest.mark.unit


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data = status, data
        self.content = b"x" if data is not None else b""

    def json(self):
        return self._data


class FakeHTTP:
    def __init__(self, token="good"):
        self.token, self.calls = token, []

    def request(self, method, url, json=None, timeout=10, headers=None):
        self.calls.append((method, url))
        if headers.get("Authorization") != f"Bearer {self.token}":
            return Resp(401, {})
        if url.endswith("/api/config"):
            return Resp(200, {"version": "2026.11.1", "location_name": "Home"})
        if url.endswith("/api/states"):
            return Resp(200, [{"entity_id": "light.a"}, {"entity_id": "sensor.b"}])
        return Resp(404, {})


def test_probe_reports_version_and_devices():
    ha = HomeAssistant("", "", session=FakeHTTP())
    out = ha.probe("http://ha.local:8123/", "good")
    assert out["ok"] and any("2026.11.1" in f for f in out["facts"]) and any("2" in f for f in out["facts"])


def test_probe_explains_missing_or_wrong_token():
    ha = HomeAssistant("", "", session=FakeHTTP())
    assert not ha.probe("", "good")["ok"]
    assert not ha.probe("http://ha.local:8123", "")["ok"]
    bad = ha.probe("http://ha.local:8123", "wrong")
    assert not bad["ok"] and bad["facts"]


def test_configure_wakes_the_stream_only_on_change():
    ha = HomeAssistant("", "", session=FakeHTTP())
    assert not ha.configured
    ha.configure("http://ha.local:8123/", "good")
    assert ha.configured and ha.url == "http://ha.local:8123" and ha._wake.is_set()
    ha._wake.clear()
    ha.configure("http://ha.local:8123", "good")
    assert not ha._wake.is_set()

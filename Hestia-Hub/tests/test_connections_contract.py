"""Shared connections contract (hestia_common.connections, docs/work/2026-11-19-unified-connections): keys go to
Hephaestus through the Hub envelope and come back by a live re-read; a card needs webui() first. No network."""
from __future__ import annotations

import pytest

from hestia_common import connections as cmod
from hestia_common.connections import ConnectError, Connections, Connector
from hestia_common.plugin_client import PluginClient

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class Card(Connector):
    id, label, group = "thing", "Thing", "home_service"

    def __init__(self):
        self.keys_seen = 0

    def state(self):
        return {"state": "off"}

    def on_keys(self):
        self.keys_seen += 1


def test_save_secrets_routes_through_hephaestus_and_sets_env(monkeypatch):
    sent = []
    monkeypatch.setattr(cmod.requests, "post", lambda url, json=None, timeout=0: sent.append((url, json)) or
                        _Resp({"status_code": 200, "payload": {"applied": True}}))
    monkeypatch.delenv("APOLLO_KEY_THING", raising=False)
    conns = Connections("apollo", "/api/images/", hub_api_url="http://hub/api")
    conns.save_secret("thing", "abc")
    url, envelope = sent[0]
    assert url == "http://hub/api/route/hephaestus/api/setup/connection-secret"
    assert envelope["body"] == {"module": "apollo", "values": {"APOLLO_KEY_THING": "abc"}}
    assert conns.secret("thing") == "abc"
    conns.save_secret("thing", "")
    assert not conns.has_key("thing")


def test_save_secrets_refused_raises_words(monkeypatch):
    monkeypatch.setattr(cmod.requests, "post", lambda *a, **k: _Resp({"status_code": 400, "payload": {"detail": "no"}}))
    with pytest.raises(ConnectError):
        Connections("apollo", "/api/images/", hub_api_url="http://hub/api").save_secret("thing", "abc")


def test_reload_keys_reads_only_its_prefix_and_tells_the_cards(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("LARES_KEY_THING=tok\nLARES_KEY_OLD=\nOTHER=x\n")
    monkeypatch.setenv("LARES_KEY_OLD", "stale")
    conns = Connections("lares", "/api/home/", env_file=env)
    card = conns.register(Card())
    assert conns.reload_keys() == ["LARES_KEY_THING"]
    assert conns.secret("thing") == "tok" and not conns.has_key("old") and card.keys_seen == 1


def test_plugin_client_connections_need_webui_with_the_same_prefix():
    conns = Connections("lares", "/api/home/")
    conns.register(Card())
    with pytest.raises(Exception):
        PluginClient("lares", title="Lares").connections(conns)
    with pytest.raises(Exception):
        PluginClient("lares", title="Lares").webui(entry="", api_prefix="/api/other/").connections(conns)
    mod = PluginClient("lares", title="Lares").webui(entry="", api_prefix="/api/home/").connections(conns)
    rows = mod.manifest()["clients"]["webui"]["connection"]
    assert rows[0]["source"] == "/api/home/connections" and rows[0]["group"] == "home_service"

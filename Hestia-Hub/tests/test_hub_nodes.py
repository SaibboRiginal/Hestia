"""Tests — machines: pairing, join token, satellite relay (docs/work/2026-10-30-setup-un-click §4.0)."""
from __future__ import annotations

import json

import pytest

from modules import relay
from modules.nodes import NodeError, Nodes


@pytest.mark.unit
class TestNodes:
    def test_join_with_code_then_token_admits_only_own_address(self, tmp_path):
        n = Nodes(tmp_path / "nodes.json")
        code = n.new_code()["code"]
        joined = n.join(code, "PC studio", "192.168.1.20")
        assert joined["token"] and joined["node_id"]
        assert n.admit(joined["token"], "http://192.168.1.20:19021")["name"] == "PC studio"
        with pytest.raises(NodeError) as wrong_host:
            n.admit(joined["token"], "http://192.168.1.99:19021")
        assert wrong_host.value.status == 403
        with pytest.raises(NodeError) as bad:
            n.admit("nope", "http://192.168.1.20:19021")
        assert bad.value.status == 401

    def test_code_is_single_use_and_burns_after_tries(self, tmp_path):
        n = Nodes(tmp_path / "nodes.json")
        code = n.new_code()["code"]
        n.join(code, "a", "10.0.0.2")
        with pytest.raises(NodeError):
            n.join(code, "b", "10.0.0.3")                  # used
        n.new_code()
        for _ in range(5):
            with pytest.raises(NodeError):
                n.join("000000x", "b", "10.0.0.3")
        assert not n._code                                   # burned

    def test_tokens_survive_restart_hashed_and_revoke(self, tmp_path):
        n = Nodes(tmp_path / "nodes.json")
        joined = n.join(n.new_code()["code"], "a", "10.0.0.2")
        assert joined["token"] not in (tmp_path / "nodes.json").read_text()
        again = Nodes(tmp_path / "nodes.json")
        assert again.check(joined["token"])
        again.revoke(joined["node_id"])
        assert Nodes(tmp_path / "nodes.json").check(joined["token"]) is None
        assert "token_sha256" not in json.dumps(again.list())

    @pytest.mark.parametrize("address", ["", "http://x", "a b", "x:1"])
    def test_address_must_be_bare_host(self, tmp_path, address):
        n = Nodes(tmp_path / "nodes.json")
        with pytest.raises(NodeError):
            n.join(n.new_code()["code"], "a", address)


@pytest.mark.unit
def test_satellite_copy_answers_first_then_central_is_fallback():
    import time
    from modules.registry import ServiceRegistry
    reg = ServiceRegistry()
    reg.register({"name": "echo", "base_url": "http://10.0.0.2:19021", "node": "n1"})
    reg.register({"name": "echo", "base_url": "http://hestia_echo:19021"})      # newer, but local
    assert reg.get("echo")[0]["base_url"] == "http://10.0.0.2:19021"
    for it in reg._services["echo"]:
        if it.get("node"):
            it["updated_at"] = time.time() - 600                                    # satellite gone quiet
    assert reg.get("echo")[0]["base_url"] == "http://hestia_echo:19021"


@pytest.mark.unit
class TestRelay:
    def test_rewrite_keeps_port_and_path(self):
        assert relay.rewrite("http://hestia_echo:19021", "192.168.1.20") == "http://192.168.1.20:19021"
        assert relay.rewrite("http://hestia_echo:19021/mcp", "pc.local") == "http://pc.local:19021/mcp"

    def test_registration_rewrites_base_and_capability_urls(self):
        m = relay.RelayMiddleware(None, {"upstream": "http://c:19001/api", "token": "t", "address": "10.0.0.2"})
        body = json.dumps({"name": "echo", "base_url": "http://hestia_echo:19021",
                           "capabilities": {"mcp_endpoint": "http://hestia_echo:19021/mcp", "voice": {"api": "/api/voice"},
                                            "ui": ["http://hestia_echo:19021/ui/webui/echo.js"]}}).encode()
        out = json.loads(m._registration(body))
        assert out["base_url"] == "http://10.0.0.2:19021"
        assert out["capabilities"]["mcp_endpoint"] == "http://10.0.0.2:19021/mcp"
        assert out["capabilities"]["ui"] == ["http://10.0.0.2:19021/ui/webui/echo.js"]
        assert out["capabilities"]["voice"] == {"api": "/api/voice"}


@pytest.mark.api
class TestNodesApi:
    @pytest.fixture(autouse=True)
    def _client(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch
        from fastapi.testclient import TestClient
        with patch("requests.post"), patch("requests.get"):
            import src.main as hub_main
        monkeypatch.setattr(hub_main, "nodes", hub_main.Nodes(tmp_path / "nodes.json"))   # src.modules copy: its NodeError
        monkeypatch.setattr("requests.post", lambda *a, **kw: MagicMock(status_code=200))
        monkeypatch.setattr("requests.get", lambda *a, **kw: MagicMock(status_code=200))
        self.hub = hub_main
        self.client = TestClient(hub_main.app)

    def test_pair_join_register_list_revoke(self):
        code = self.client.post("/api/nodes/pair").json()["code"]
        joined = self.client.post("/api/nodes/join", json={"code": code, "name": "PC", "address": "10.9.9.9"}).json()
        reg = {"name": "nodetest", "base_url": "http://10.9.9.9:19021", "tags": ["core"]}
        assert self.client.post("/api/registry/register", json=reg,
                                headers={"X-Hestia-Node-Token": "bad"}).status_code == 401
        assert self.client.post("/api/registry/register", json=reg,
                                headers={"X-Hestia-Node-Token": joined["token"]}).status_code == 200
        listed = self.client.get("/api/nodes").json()["nodes"]
        assert listed[0]["name"] == "PC" and listed[0]["modules"] == [{"name": "nodetest", "online": True}]
        assert self.client.delete(f"/api/nodes/{joined['node_id']}").json()["revoked"] == "PC"
        assert not self.hub.registry.get("nodetest")

    def test_join_with_wrong_code(self):
        self.client.post("/api/nodes/pair")
        resp = self.client.post("/api/nodes/join", json={"code": "nope", "name": "PC", "address": "10.9.9.9"})
        assert resp.status_code == 403

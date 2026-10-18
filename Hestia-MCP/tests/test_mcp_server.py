"""Tests — Hestia's one MCP server (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B2)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.catalog as catalog_mod
import core.mcp_server as server_mod
from core.catalog import ToolCatalog
from core.mcp_server import MCPServer
from hestia_common.mcp_client import MCPClient, as_command
from hestia_common.tool_call import build_request

COMMANDS = [
    {"command": "forge_tasks", "title": "Task di sviluppo", "description": "List tasks", "service": "hephaestus",
     "method": "GET", "path": "/api/forge/tasks", "clients": ["*"],
     "arguments_schema": {"limit": {"type": "integer", "description": "n", "required": False}}},
    {"command": "forge_approve", "service": "hephaestus", "method": "POST",
     "path": "/api/forge/tasks/$task_id/approve", "clients": ["telegram"]},
    {"command": "agenda_add", "service": "chronos", "method": "POST", "path": "/api/agenda/items",
     "body_template": {"title": "$arg.title", "owner": "$owner"}},
]


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


@pytest.fixture
def rig(monkeypatch):
    routed = []
    monkeypatch.setattr(catalog_mod.requests, "get", lambda url, timeout=0: _Resp({"commands": COMMANDS}))

    def _post(url, json=None, timeout=0):
        routed.append((url, json))
        return _Resp({"status_code": 200, "payload": [{"id": "t1"}]})
    monkeypatch.setattr(server_mod.requests, "post", _post)
    values = {"mcp.tools.cache_ttl": 60, "mcp.discovery.hub_timeout": 8, "mcp.calls.timeout": 10}
    monkeypatch.setattr(catalog_mod.settings, "get", lambda k: values[k])
    monkeypatch.setattr(server_mod.settings, "get", lambda k: values[k])
    app = FastAPI()
    app.include_router(MCPServer(ToolCatalog("http://hub/api"), "http://hub/api").router())
    return TestClient(app), routed


def _rpc(client, method, params=None, who="", msg_id=1):
    headers = {"X-Hestia-Client": who} if who else {}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
                       headers=headers).json()


@pytest.mark.api
class TestProtocol:
    def test_initialize_negotiates_version(self, rig):
        c, _ = rig
        res = _rpc(c, "initialize", {"protocolVersion": "2025-03-26"})["result"]
        assert res["protocolVersion"] == "2025-03-26" and res["capabilities"]["tools"] is not None
        assert _rpc(c, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"

    def test_notification_and_batch(self, rig):
        c, _ = rig
        assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
        out = c.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                   {"jsonrpc": "2.0", "id": 2, "method": "nope"}]).json()
        assert out[0]["result"] == {} and out[1]["error"]["code"] == -32601
        assert c.get("/mcp").status_code == 405


@pytest.mark.api
class TestTools:
    def test_list_filters_by_client_and_keeps_hestia_meta(self, rig):
        c, _ = rig
        webui = [t["name"] for t in _rpc(c, "tools/list", who="webui")["result"]["tools"]]
        assert "forge_tasks" in webui and "forge_approve" not in webui
        tools = {t["name"]: t for t in _rpc(c, "tools/list", who="telegram")["result"]["tools"]}
        assert tools["forge_approve"]["inputSchema"]["required"] == ["task_id"]
        assert tools["forge_approve"]["annotations"]["readOnlyHint"] is False
        assert tools["forge_tasks"]["annotations"]["readOnlyHint"] is True
        assert tools["agenda_add"]["inputSchema"]["properties"] == {"title": {"type": "string", "description": "title"}}
        assert tools["forge_tasks"]["_meta"]["hestia"]["service"] == "hephaestus"

    def test_call_routes_through_hub_with_context(self, rig):
        c, routed = rig
        res = _rpc(c, "tools/call", {"name": "agenda_add", "arguments": {"title": "Dentista"},
                                     "_meta": {"hestia": {"session_id": "s1", "notify_target": "owner",
                                                          "client": "webui"}}}, who="oracle")["result"]
        assert res["isError"] is False and res["structuredContent"] == {"result": [{"id": "t1"}]}
        url, env = routed[-1]
        assert url == "http://hub/api/route/chronos/api/agenda/items"
        assert env["body"] == {"title": "Dentista", "owner": "owner"}
        assert env["headers"] == {"X-Session-Id": "s1", "X-Hestia-Client": "webui"}

    def test_hidden_tool_cannot_be_called(self, rig):
        c, _ = rig
        err = _rpc(c, "tools/call", {"name": "forge_approve", "arguments": {"task_id": "x"}}, who="webui")["error"]
        assert err["code"] == -32602


@pytest.mark.unit
class TestSharedRules:
    def test_build_request_paths_templates_and_rest(self):
        req = build_request({"service": "hephaestus", "method": "POST", "path": "/api/forge/tasks/$task_id/approve"},
                            {"task_id": "a b", "note": "x"}, {"session_id": "s"})
        assert req["path"] == "api/forge/tasks/a%20b/approve" and req["body"] == {"note": "x"}
        req = build_request({"service": "x", "method": "GET", "path": "/a/{id}"}, {"id": 3, "f": 1})
        assert req["path"] == "a/3" and req["query"] == {"f": 1} and req["body"] is None

    def test_client_unwraps_and_converts(self, rig, monkeypatch):
        c, _ = rig
        import hestia_common.mcp_client as mc
        module_call = server_mod.requests.post   # the rig's fake for module routes (same requests module)

        def _hub(url, json=None, timeout=0):
            if not url.endswith("/route/mcp/mcp"):
                return module_call(url, json=json, timeout=timeout)
            resp = c.post("/mcp", json=json["body"], headers=json["headers"])
            return _Resp({"status_code": resp.status_code, "payload": resp.json()})
        monkeypatch.setattr(mc.requests, "post", _hub)
        client = MCPClient("http://hub/api", client="telegram")
        cmds = {cm["command"]: cm for cm in (as_command(t) for t in client.list_tools())}
        assert cmds["forge_approve"]["path"] == "/api/forge/tasks/$task_id/approve" and cmds["forge_approve"]["writes"]
        assert client.call("forge_tasks", {"limit": 1}) == (True, [{"id": "t1"}])

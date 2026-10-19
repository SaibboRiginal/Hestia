"""Tests — Comandi page reads/calls (/api/mcp/ui/tools…, SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.catalog as catalog_mod
import core.mcp_server as server_mod
import core.ui_tools as ui_mod
from core.catalog import ToolCatalog
from core.mcp_server import MCPServer
from core.ui_tools import UiTools, as_command

COMMANDS = [
    {"command": "forge_tasks", "title": "Task di sviluppo", "description": "List tasks", "service": "hephaestus",
     "method": "GET", "path": "/api/forge/tasks", "clients": ["*"], "response_mode": "raw_json",
     "arguments_schema": {"limit": {"type": "integer", "description": "n", "required": True}}},
    {"command": "forge_approve", "service": "hephaestus", "method": "POST",
     "path": "/api/forge/tasks/$task_id/approve", "clients": ["telegram"]},
    {"command": "agenda_add", "service": "chronos", "method": "POST", "path": "/api/agenda/items", "clients": ["ui"],
     "body_template": {"title": "$arg.title"}},
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
    answers = {"payload": [{"id": "t1"}], "status": 200}
    monkeypatch.setattr(catalog_mod.requests, "get", lambda url, timeout=0: _Resp({"commands": COMMANDS}))

    def _post(url, json=None, timeout=0):
        routed.append((url, json))
        if "/route/oracle/api/format" in url:
            return _Resp({"status_code": 200, "payload": {"text": "Hai 1 task."}})
        return _Resp({"status_code": answers["status"], "payload": answers["payload"]})
    monkeypatch.setattr(server_mod.requests, "post", _post)
    monkeypatch.setattr(ui_mod.requests, "post", _post)
    values = {"mcp.tools.cache_ttl": 60, "mcp.discovery.hub_timeout": 8, "mcp.calls.timeout": 10}
    monkeypatch.setattr(catalog_mod.settings, "get", lambda k: values[k])
    monkeypatch.setattr(server_mod.settings, "get", lambda k: values[k])
    app = FastAPI()
    app.include_router(UiTools(MCPServer(ToolCatalog("http://hub/api"), "http://hub/api"), "http://hub/api").router())
    return TestClient(app), routed, answers


@pytest.mark.unit
def test_as_command_shape():
    tool = {"name": "x_do", "title": "Fai", "inputSchema": {"type": "object", "properties": {"a": {"type": "string"}}},
            "annotations": {"readOnlyHint": False}, "_meta": {"hestia": {"service": "x", "method": "POST", "path": "/p"}}}
    c = as_command(tool)
    assert (c["command"], c["service"], c["method"], c["path"], c["writes"]) == ("x_do", "x", "POST", "/p", True)
    assert c["response_mode"] == "oracle_natural" and c["arguments_schema"]["properties"] == {"a": {"type": "string"}}


@pytest.mark.api
class TestUiTools:
    def test_list_is_what_the_webui_sees(self, rig):
        c, _, _ = rig
        body = c.get("/api/mcp/ui/tools").json()
        names = {x["command"] for x in body["commands"]}
        assert names == {"forge_tasks", "agenda_add"}          # forge_approve is telegram-only
        assert body["count"] == 2 and body["services"] == ["chronos", "hephaestus"]
        tasks = next(x for x in body["commands"] if x["command"] == "forge_tasks")
        assert tasks["writes"] is False and tasks["arguments_schema"]["required"] == ["limit"]
        assert next(x for x in body["commands"] if x["command"] == "agenda_add")["writes"] is True

    def test_call_routes_as_webui(self, rig):
        c, routed, _ = rig
        out = c.post("/api/mcp/ui/tools/call", json={"command": "forge_tasks", "args": {"limit": 3}}).json()
        assert out["ok"] is True and out["result"] == [{"id": "t1"}] and out["response_mode"] == "raw_json"
        url, env = routed[-1]
        assert url.endswith("/route/hephaestus/api/forge/tasks")
        assert env["headers"].get("X-Hestia-Client") == "webui" and env["query"] == {"limit": 3}
        assert env["timeout_seconds"] <= 20

    def test_hidden_or_unknown_tool_is_404(self, rig):
        c, _, _ = rig
        assert c.post("/api/mcp/ui/tools/call", json={"command": "forge_approve", "args": {}}).status_code == 404
        assert c.post("/api/mcp/ui/tools/call", json={"command": "nope"}).status_code == 404
        assert c.post("/api/mcp/ui/tools/call", json={"command": " "}).status_code == 400

    def test_module_error_is_reported(self, rig):
        c, _, answers = rig
        answers.update(status=422, payload={"detail": "limit troppo alto"})
        out = c.post("/api/mcp/ui/tools/call", json={"command": "forge_tasks", "args": {"limit": 999}}).json()
        assert out["ok"] is False and out["error"] == "limit troppo alto" and out["status_code"] == 422

    def test_format_goes_to_oracle_through_hub(self, rig):
        c, routed, _ = rig
        out = c.post("/api/mcp/ui/tools/format", json={"command": "forge_tasks", "result": [{"id": "t1"}]}).json()
        assert out == {"ok": True, "text": "Hai 1 task."}
        url, env = routed[-1]
        assert url == "http://hub/api/route/oracle/api/format"
        assert env["body"]["client"] == "webui" and env["body"]["payload"] == [{"id": "t1"}]

    def test_format_failure_is_soft(self, rig, monkeypatch):
        c, _, _ = rig
        def _boom(*a, **k):
            raise ConnectionError("down")
        monkeypatch.setattr(ui_mod.requests, "post", _boom)
        assert c.post("/api/mcp/ui/tools/format", json={"command": "x", "result": {}}).json() == {"ok": False, "text": ""}

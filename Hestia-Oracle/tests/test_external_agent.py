"""External brain mode (dossier 2026-10-19-oracle-a-blocchi §D): mode per use case, the MCP bridge, the session
cache, Claude Code and Codex adapters with fake CLIs, engine fallback. No real CLI or network."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from core.agent_loop import ToolDefinition
from core.services import external_agent, mcp_bridge, oracle_settings


def _set(monkeypatch, key, value):
    monkeypatch.setitem(oracle_settings.settings._effective, key, value)


@pytest.fixture(autouse=True)
def _clean():
    external_agent._runs.clear()
    external_agent._sessions.clear()
    external_agent._internal_at.clear()
    yield


def _tool(name="calendar_list", writes=False):
    calls = []

    def handler(**params):
        calls.append(params)
        return True, {"items": [1, 2], "confirm": None}
    return ToolDefinition(name=name, description="Lista", parameters={"type": "object"}, handler=handler,
                          writes=writes), calls


class _FakeAgent:
    DEFAULT_MODEL = "sonnet"
    runs: list = []
    session = "agent-s1"

    @classmethod
    def available(cls):
        return True, "ok"

    @classmethod
    def run(cls, *, model, system, prompt, resume, bridge):
        cls.runs.append({"prompt": prompt, "resume": resume, "bridge": bridge, "system": system})
        if bridge:   # the agent calls a tool through the bridge's token
            token = bridge["env"]["HESTIA_BRIDGE_URL"].rsplit("/", 1)[1]
            external_agent.call_tool(token, "calendar_list", {"day": "oggi"})
        return {"text": "fatto", "session_id": cls.session, "usage": {"input": 50, "cached": 10, "output": 5}}


@pytest.fixture
def fake(monkeypatch):
    _FakeAgent.runs = []
    monkeypatch.setitem(external_agent._ADAPTERS, "claude", _FakeAgent)
    _set(monkeypatch, oracle_settings.BRAIN_AGENT, "claude")
    _set(monkeypatch, oracle_settings.BRAIN_MODEL, "sonnet")
    return _FakeAgent


@pytest.mark.unit
class TestMode:
    def test_global_and_per_use_case(self, monkeypatch):
        assert external_agent.mode_for("oracle.generale") == "interna"
        _set(monkeypatch, oracle_settings.BRAIN_MODE, "esterna")
        assert external_agent.mode_for("oracle.generale") == "esterna"
        _set(monkeypatch, oracle_settings.USECASES_KEY, {"scout.annunci": {"mode": "interna"}})
        assert external_agent.mode_for("scout.annunci") == "interna"


@pytest.mark.unit
class TestTurn:
    def test_tools_through_bridge_and_session_cache(self, fake):
        from core.services import llm_usage
        tool, calls = _tool()
        answer, log = external_agent.run_turn(session_id="s1", user_message="cosa ho oggi?", system_prompt="SYS",
                                              primer="CONVERSATION HISTORY:\nUSER: ciao", tools=[tool])
        assert answer == "fatto" and calls == [{"day": "oggi"}]
        assert log[0]["tool"] == "calendar_list" and log[0]["ok"]
        assert "CONVERSATION HISTORY" in fake.runs[0]["prompt"] and fake.runs[0]["resume"] == ""
        assert not external_agent._runs   # the token dies with the turn
        external_agent.run_turn(session_id="s1", user_message="e domani?", system_prompt="SYS", primer="H",
                                tools=[tool])
        assert fake.runs[1]["resume"] == "agent-s1" and fake.runs[1]["prompt"] == "e domani?"
        row = llm_usage.captured[-1]
        assert (row["chain"], row["provider"], row["input_tokens"], row["cost_kind"]) == (
            "agente:claude", "claude", 50, "abbonamento")

    def test_internal_turn_invalidates_cache(self, fake):
        tool, _ = _tool()
        external_agent.run_turn(session_id="s1", user_message="a", system_prompt="", primer="H", tools=[tool])
        external_agent.note_internal_turn("s1")
        external_agent.run_turn(session_id="s1", user_message="b", system_prompt="", primer="H2", tools=[tool])
        assert fake.runs[1]["resume"] == "" and fake.runs[1]["prompt"].startswith("H2")

    def test_unavailable_agent_raises(self, monkeypatch):
        _set(monkeypatch, oracle_settings.BRAIN_AGENT, "codex")
        monkeypatch.setattr(external_agent.shutil, "which", lambda _b: None)
        with pytest.raises(external_agent.AgentError, match="codex CLI not installed"):
            external_agent.run_turn(session_id="s", user_message="x", system_prompt="", primer="", tools=[])


@pytest.mark.unit
class TestBridge:
    def test_jsonrpc_forwarding(self):
        seen = []

        def http(method, path, body=None):
            seen.append((method, path, body))
            return {"tools": [{"name": "t"}]} if path == "/tools" else {"ok": False, "result": "no"}
        init = mcp_bridge.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, http)
        assert init["result"]["serverInfo"]["name"] == "hestia"
        assert mcp_bridge.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, http) is None
        assert mcp_bridge.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, http)["result"]["tools"][0]["name"] == "t"
        out = mcp_bridge.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                 "params": {"name": "t", "arguments": {"a": 1}}}, http)
        assert out["result"]["isError"] is True and seen[-1] == ("POST", "/call", {"name": "t", "params": {"a": 1}})
        assert mcp_bridge.handle({"jsonrpc": "2.0", "id": 4, "method": "nope"}, http)["error"]["code"] == -32601

    def test_bridge_endpoints_loopback_only(self):
        from unittest.mock import MagicMock, patch
        from fastapi.testclient import TestClient
        with patch("core.oracle_engine.OracleEngine", return_value=MagicMock()), patch("requests.post"):
            import main
            client = TestClient(main.app)
        tool, calls = _tool()
        token = external_agent.open_run([tool])
        assert client.get(f"/api/agent-bridge/{token}/tools").json()["tools"][0]["name"] == "calendar_list"
        assert client.post(f"/api/agent-bridge/{token}/call", json={"name": "calendar_list", "params": {}}).json()["ok"]
        assert client.get("/api/agent-bridge/nope/tools").status_code == 404
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as err:
            main._bridge_guard(NS(client=NS(host="10.0.0.5")))
        assert err.value.status_code == 403


@pytest.mark.unit
class TestAdapters:
    def test_claude_command_and_parse(self, monkeypatch):
        cmd = external_agent.ClaudeCodeAgent.command("sonnet", "SYS", "r1", "/tmp/m.json")
        assert cmd[cmd.index("--tools") + 1] == "" and "--allowedTools" in cmd and cmd[-2:] == ["--resume", "r1"]
        out = json.dumps({"result": "ok", "session_id": "abc", "total_cost_usd": 0.01,
                          "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 7}})
        monkeypatch.setattr(external_agent, "_subprocess", lambda c, p, t: NS(returncode=0, stdout=out, stderr=""))
        res = external_agent.ClaudeCodeAgent.run(model="sonnet", system="", prompt="x", resume="", bridge={"command": "py"})
        assert res["session_id"] == "abc" and res["usage"]["input"] == 105 and res["usage"]["cached"] == 100

    def test_codex_jsonl_parse_and_resume(self, monkeypatch):
        bridge = {"command": "/usr/bin/python3", "args": ["-m", "x"], "env": {"HESTIA_BRIDGE_URL": "u"}}
        cmd = external_agent.CodexAgent.command("gpt-5-codex", "t1", bridge)
        assert cmd[1:4] == ["exec", "resume", "t1"] and 'mcp_servers.hestia.env={HESTIA_BRIDGE_URL = "u"}' in cmd
        lines = "\n".join(json.dumps(e) for e in [
            {"type": "thread.started", "thread_id": "t9"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "ciao"}},
            {"type": "turn.completed", "usage": {"input_tokens": 9, "cached_input_tokens": 3, "output_tokens": 2}}])
        monkeypatch.setattr(external_agent, "_subprocess", lambda c, p, t: NS(returncode=0, stdout=lines, stderr=""))
        res = external_agent.CodexAgent.run(model="", system="S", prompt="x", resume="", bridge=None)
        assert (res["text"], res["session_id"], res["usage"]["cached"]) == ("ciao", "t9", 3)

    def test_codex_failure_raises(self, monkeypatch):
        bad = json.dumps({"type": "turn.failed", "error": {"message": "usage limit"}})
        monkeypatch.setattr(external_agent, "_subprocess", lambda c, p, t: NS(returncode=1, stdout=bad, stderr=""))
        with pytest.raises(external_agent.AgentError, match="usage limit"):
            external_agent.CodexAgent.run(model="", system="", prompt="x", resume="", bridge=None)

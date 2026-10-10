"""Tests — Claude provider types (anthropic API key, claude_cli subscription).

All network and subprocess calls mocked.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from agents.providers.anthropic_api import AnthropicProvider
from agents.providers.base import think_level
from agents.providers.claude_cli import ClaudeCliProvider


class _FakeMessages:
    def __init__(self, content, stop_reason="end_turn"):
        self.calls: list[dict] = []
        self._content = content
        self._stop = stop_reason

    def create(self, **params):
        self.calls.append(params)
        usage = NS(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return NS(content=self._content, stop_reason=self._stop, usage=usage)


def _anthropic(content, stop_reason="end_turn"):
    prov = AnthropicProvider({"api_key": "k"})
    fake = _FakeMessages(content, stop_reason)
    prov._client = NS(messages=fake)
    return prov, fake


@pytest.mark.unit
class TestThinkLevel:
    def test_levels(self):
        assert think_level(False) == "fast"
        assert think_level(None) == "fast"
        assert think_level(True) == "normal"
        assert think_level("deep") == "deep"


@pytest.mark.unit
class TestAnthropicProvider:
    def test_unavailable_without_key(self):
        assert AnthropicProvider({"api_key": ""}).available()[0] is False

    def test_tool_call_and_reasoning(self):
        prov, fake = _anthropic([NS(type="thinking", thinking="penso"),
                                 NS(type="tool_use", name="cal", input={"q": "oggi"})], "tool_use")
        out = prov.ask_with_tools("claude-haiku-5-5", "sys", "prompt",
                                  [{"name": "cal", "description": "d", "parameters": {"type": "object"}}], True)
        assert out["tool_call"] == {"name": "cal", "params": {"q": "oggi"}}
        assert out["reasoning_content"] == "penso"
        tools = fake.calls[0]["tools"]
        assert tools[0]["input_schema"] == {"type": "object"}
        assert tools[-1]["cache_control"] == {"type": "ephemeral"}

    def test_mode_maps_to_thinking(self):
        prov, fake = _anthropic([NS(type="text", text="ciao")])
        assert prov.ask("m", "sys", "p", False) == "ciao"
        assert fake.calls[-1]["thinking"] == {"type": "disabled"}
        prov.ask("m", "sys", "p", "deep")
        assert fake.calls[-1]["thinking"]["type"] == "adaptive"
        assert fake.calls[-1]["output_config"] == {"effort": "high"}

    def test_static_prefix_is_cached(self):
        prov, fake = _anthropic([NS(type="text", text="ok")])
        prov.ask("m", "", "STATIC\n\nSYSTEM_PROMPT_DYNAMIC_BOUNDARY\n\nDYN", True)
        content = fake.calls[-1]["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "STATIC", "cache_control": {"type": "ephemeral"}}
        assert content[1] == {"type": "text", "text": "DYN"}
        assert "system" not in fake.calls[-1]

    def test_refusal_gives_text(self):
        prov, _ = _anthropic([], "refusal")
        assert prov.ask("m", "", "p", False)


@pytest.mark.unit
class TestClaudeCliProvider:
    def _prov(self):
        return ClaudeCliProvider({"bin": "claude", "authed": True, "env": {"PATH": "/usr/bin"}})

    def test_unavailable_without_login(self):
        with patch("agents.providers.claude_cli.shutil.which", return_value="/usr/bin/claude"):
            assert ClaudeCliProvider({"authed": False}).available()[0] is False

    def test_text_tool_calls_parsed(self):
        result = ('<tool_call>{"name": "a", "params": {"x": 1}}</tool_call>\n'
                  '<tool_call>{"name": "b", "params": {}}</tool_call>')
        proc = NS(returncode=0, stdout=json.dumps({"result": result, "is_error": False}), stderr="")
        with patch("agents.providers.claude_cli.shutil.which", return_value="/usr/bin/claude"), \
                patch("agents.providers.claude_cli.subprocess.run", return_value=proc) as run:
            out = self._prov().ask_with_tools("haiku", "sys", "prompt",
                                              [{"name": "a", "description": "d"}], "deep")
        assert [c["name"] for c in out["tool_calls"]] == ["a", "b"]
        cmd = run.call_args.args[0]
        assert cmd[cmd.index("--tools") + 1] == ""
        assert cmd[cmd.index("--effort") + 1] == "high"
        assert "--strict-mcp-config" in cmd
        assert run.call_args.kwargs["env"] == {"PATH": "/usr/bin"}

    def test_cli_error_raises(self):
        proc = NS(returncode=1, stdout="", stderr="boom")
        with patch("agents.providers.claude_cli.shutil.which", return_value="/usr/bin/claude"), \
                patch("agents.providers.claude_cli.subprocess.run", return_value=proc):
            with pytest.raises(RuntimeError):
                self._prov().ask("haiku", "", "p")


@pytest.mark.unit
def test_cli_env_has_no_anthropic_keys(monkeypatch):
    from agents.llm_config import cli_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("ORACLE_ANTHROPIC_API_KEY", "b")
    env = cli_env()
    assert "ANTHROPIC_API_KEY" not in env and "ORACLE_ANTHROPIC_API_KEY" not in env

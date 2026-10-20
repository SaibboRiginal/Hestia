"""Tests — Oracle on local models: real context window, cache telemetry, cache-friendly prompts,
OpenAI-compatible provider (dossier docs/work/2026-10-10-oracle-local-context).

All network calls mocked.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

import core.agent_loop as al
from agents.providers import PROVIDER_TYPES, get_provider
from agents.providers.openai_compat import OpenAICompatProvider
from agents.universal_agent import UniversalAgent
from core.agent_loop import ScratchMessage, _stub_old_tool_results
from core.services import llm_stats, oracle_settings, prompt_config
from core.services.context_builder import ContextBuilder


@pytest.fixture(autouse=True)
def _clean_stats():
    llm_stats.reset()
    al._token_ratio_cache["m1"] = 3.0  # no Ollama /api/tokenize calibration
    yield
    llm_stats.reset()


def _resp(payload: dict) -> MagicMock:
    r = MagicMock()
    r.json.return_value = payload
    return r


# ── A: num_ctx + keep_alive ─────────────────────────────────────────────────

@pytest.mark.unit
class TestOllamaOptions:
    def test_defaults(self):
        assert oracle_settings.ollama_request_options() == {"options": {"num_ctx": 8192}, "keep_alive": "30m"}

    def test_settings_and_always(self, monkeypatch):
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.NUM_CTX, 16384)
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.KEEP_ALIVE, "always")
        assert oracle_settings.ollama_request_options() == {"options": {"num_ctx": 16384}, "keep_alive": -1}

    def test_every_ollama_call_sends_them(self):
        agent = UniversalAgent("SYS", "ollama", "m1", thinking=False)
        with patch("agents.universal_agent.requests.post", return_value=_resp({"response": "ok"})) as post:
            agent.ask("ciao")
        body = post.call_args.kwargs["json"]
        assert body["options"]["num_ctx"] == 8192 and body["keep_alive"] == "30m"

    def test_tool_call_sends_them(self):
        agent = UniversalAgent("SYS", "ollama", "m1", thinking=False)
        data = {"message": {"content": "", "tool_calls": [{"function": {"name": "t", "arguments": {}}}]}}
        with patch("agents.universal_agent.requests.post", return_value=_resp(data)) as post:
            out = agent.ask_with_tools("q", [{"name": "t", "description": "d"}])
        assert out["tool_call"]["name"] == "t"
        assert post.call_args.kwargs["json"]["options"]["num_ctx"] == 8192


# ── B: stats ────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestStats:
    def test_ollama_stats_recorded_per_label(self):
        agent = UniversalAgent("SYS", "ollama", "m1", thinking=False, label="generic")
        data = {"response": "ok", "prompt_eval_count": 10, "prompt_eval_duration": 5_000_000,
                "load_duration": 2_000_000_000, "eval_count": 20, "eval_duration": 1_000_000_000}
        with patch("agents.universal_agent.requests.post", return_value=_resp(data)):
            agent.ask("x" * 900)
        row = llm_stats.summary()["generic"]
        assert row["calls"] == 1 and row["cache_estimated"] is True
        assert row["avg_load_ms"] == 2000 and row["tokens_per_second"] == 20.0
        assert row["cache_hit_pct"] > 90  # 10 of ~300 tokens evaluated

    def test_openai_usage_and_timings(self):
        row = llm_stats.record_openai("code", "m", {
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
            "timings": {"cache_n": 80, "prompt_n": 20, "prompt_ms": 30.0, "predicted_n": 5, "predicted_ms": 100.0}})
        assert row["prompt_tokens"] == 100 and row["cached_tokens"] == 80
        assert llm_stats.summary()["code"]["cache_hit_pct"] == 80.0

    def test_cached_tokens_detail(self):
        llm_stats.record_openai("x", "m", {"usage": {"prompt_tokens": 50, "completion_tokens": 2,
                                                     "prompt_tokens_details": {"cached_tokens": 40}}})
        assert llm_stats.summary()["x"]["cache_hit_pct"] == 80.0

    def test_no_usage_no_row(self):
        assert llm_stats.record_openai("x", "m", {"choices": []}) is None
        assert llm_stats.record_ollama("x", "m1", {"response": "ok"}, 10) is None


# ── C: cache-friendly prompts ───────────────────────────────────────────────

@pytest.mark.unit
class TestToolResultStubs:
    def _pad(self):
        return [ScratchMessage("tool", "[a] → ✅ first line\nlots of rows", 0),
                ScratchMessage("assistant", "thinking"),
                ScratchMessage("tool", "[b] → ✅ recent", 3)]

    def test_old_results_stubbed_under_pressure(self):
        pad = self._pad()
        assert _stub_old_tool_results(pad, 4, 2, 60.0) == 1
        assert pad[0].stubbed and "lots of rows" not in pad[0].content and pad[0].content.startswith("[a]")
        assert pad[2].content == "[b] → ✅ recent"

    def test_nothing_without_pressure_or_when_off(self):
        assert _stub_old_tool_results(self._pad(), 4, 2, 10.0) == 0
        assert _stub_old_tool_results(self._pad(), 4, 0, 99.0) == 0


@pytest.mark.unit
class TestStableHistoryWindow:
    def test_start_moves_in_jumps(self):
        cb = ContextBuilder(6, 500, 5, 100)
        msgs = [{"id": i, "role": "user", "content": str(i)} for i in range(1, 30)]
        starts = []
        for n in range(6, 17):
            window = cb.stable_window(msgs[:n][-cb.history_fetch_limit:], "s")
            starts.append(window[0]["id"])
            assert 6 <= len(window) <= cb.history_fetch_limit
        # The window start stays put for several turns instead of moving every turn.
        assert starts == [1, 1, 1, 1, 5, 5, 5, 5, 9, 9, 9]

    def test_without_session_or_ids_is_last_n(self):
        cb = ContextBuilder(3, 500, 5, 100)
        msgs = [{"role": "user", "content": str(i)} for i in range(10)]
        assert cb.stable_window(msgs, "s") == msgs[-3:]
        assert "--- PREVIOUS CONVERSATION ---" in cb.compact_history(msgs)


# ── D: OpenAI-compatible provider ───────────────────────────────────────────

def _openai() -> OpenAICompatProvider:
    return OpenAICompatProvider({"base_url": "http://host:8080/v1", "cache_prompt": True})


@pytest.mark.unit
class TestOpenAIProvider:
    def test_named_provider_address_from_settings_key_from_env(self, monkeypatch):
        assert PROVIDER_TYPES["openai"] is OpenAICompatProvider
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.PROVIDERS_KEY,
                            {"deepseek": {"type": "openai", "url": "https://api.deepseek.com/v1"}})
        monkeypatch.setenv("ORACLE_KEY_DEEPSEEK", "sk-test")
        prov = get_provider("deepseek")
        assert prov.available()[0] and prov.config["cache_prompt"] is True
        assert prov.config["base_url"] == "https://api.deepseek.com/v1" and prov.config["api_key"] == "sk-test"

    def test_static_prefix_in_system_and_tool_calls(self):
        prompt = prompt_config.compose_with_dynamic_boundary(["STATIC"], ["DYN"])
        data = {"choices": [{"message": {"content": "", "tool_calls": [
            {"function": {"name": "t1", "arguments": json.dumps({"a": 1})}}]}}]}
        with patch("agents.providers.openai_compat.requests.post", return_value=_resp(data)) as post:
            out = _openai().ask_with_tools("mm", "SYS", prompt, [{"name": "t1", "description": "d"}], False)
        body = post.call_args.kwargs["json"]
        assert body["messages"][0] == {"role": "system", "content": "SYS\n\nSTATIC"}
        assert body["messages"][1] == {"role": "user", "content": "DYN"}
        assert body["cache_prompt"] is True and body["chat_template_kwargs"] == {"enable_thinking": False}
        assert out["tool_call"] == {"name": "t1", "params": {"a": 1}}

    def test_thinking_on_sends_no_template_switch(self):
        data = {"choices": [{"message": {"content": "ok"}}]}
        with patch("agents.providers.openai_compat.requests.post", return_value=_resp(data)) as post:
            assert _openai().ask("mm", "", "hi", True) == "ok"
        assert "chat_template_kwargs" not in post.call_args.kwargs["json"]

    def test_stream(self):
        lines = [b'data: {"choices":[{"delta":{"content":"ci"}}]}',
                 b'data: {"choices":[{"delta":{"content":"ao"}}]}',
                 b'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":2}}',
                 b"data: [DONE]"]
        resp = MagicMock()
        resp.iter_lines.return_value = lines
        resp.__enter__.return_value = resp
        prov = _openai()
        prov.label = "generic"
        with patch("agents.providers.openai_compat.requests.post", return_value=resp):
            assert "".join(prov.ask_stream("mm", "SYS", "hello")) == "ciao"
        assert llm_stats.summary()["generic"]["provider"] == "openai"

    def test_list_models(self):
        with patch("agents.providers.openai_compat.requests.get",
                   return_value=_resp({"data": [{"id": "qwen3-8b"}]})):
            assert _openai().list_models() == ["qwen3-8b"]


# ── LLM gateway: local profile through Ollama /api/chat (num_ctx honoured) ──

@pytest.mark.unit
class TestGatewayOllamaNative:
    def _body(self) -> dict:
        return {"use_case": "forge.codice", "temperature": 0.2, "tools": [{"type": "function", "function": {"name": "read_file"}}],
                "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                             {"role": "assistant", "content": "", "tool_calls": [
                                 {"id": "c1", "type": "function",
                                  "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"}}]},
                             {"role": "tool", "tool_call_id": "c1", "content": "1\tx"}]}

    def test_native_request_and_openai_response(self, monkeypatch):
        from core.services import llm_gateway
        monkeypatch.setenv("OLLAMA_URL", "http://ollama:11434/api/generate")
        reply = {"model": "m1", "done_reason": "stop", "prompt_eval_count": 100, "eval_count": 5,
                 "message": {"role": "assistant", "content": "", "thinking": "hmm",
                             "tool_calls": [{"function": {"name": "finish", "arguments": {"summary": "ok"}}}]}}
        with patch("core.services.llm_gateway.requests.post", return_value=_resp(reply)) as post:
            post.return_value.status_code = 200
            out = llm_gateway.chat(self._body())
        url, sent = post.call_args.args[0], post.call_args.kwargs["json"]
        assert url == "http://ollama:11434/api/chat"
        assert sent["options"]["num_ctx"] == oracle_settings.context_window()
        assert sent["options"]["temperature"] == 0.2
        assert sent["messages"][2]["tool_calls"][0]["function"]["arguments"] == {"path": "a.py"}
        msg = out["choices"][0]["message"]
        assert out["choices"][0]["finish_reason"] == "tool_calls"
        assert msg["reasoning_content"] == "hmm"
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"summary": "ok"}

    def test_length_when_window_full(self):
        from core.services.llm_gateway import _openai_response
        out = _openai_response({"done_reason": "length", "message": {"content": "cut"}}, "m1")
        assert out["choices"][0]["finish_reason"] == "length"

    def test_usecase_status_reports_window(self):
        from core.services import llm_gateway
        status = llm_gateway.usecase_status("forge.codice")
        assert status["available"] and status["provider"] == "ollama"
        assert status["context_window"] == oracle_settings.context_window()
        assert status["billed"] is False   # no keys in tests: only the local step is usable

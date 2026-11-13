"""Tests — the window of a local model is read from its program, not imposed
(dossier docs/work/2026-11-12-contesto-e-scorciatoie §3.1). All network calls mocked."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import core.agent_loop as al
from core.services import llm_stats, local_window, oracle_settings


@pytest.fixture(autouse=True)
def _clean():
    local_window.reset()
    llm_stats.reset()
    al._token_ratio_cache[""] = 3.0
    yield
    local_window.reset()
    llm_stats.reset()


def _ps(*models: tuple[str, int]) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {"models": [{"name": n, "context_length": c} for n, c in models]}
    return r


def _call(model: str, ps: MagicMock) -> None:
    """One Ollama call followed by the read of /api/ps (run inline instead of in its thread)."""
    sent = local_window.ollama_num_ctx(model)
    with patch("core.services.local_window.threading.Thread"):
        local_window.note_call(model, sent)
    with patch("core.services.local_window.requests.get", return_value=ps):
        local_window.refresh_ollama()


@pytest.mark.unit
class TestOllamaWindow:
    def test_before_any_read_falls_back_and_sends_nothing(self):
        assert local_window.ollama_num_ctx("gemma") == 0
        assert local_window.ollama_window("gemma") == local_window.FLOOR
        assert local_window.source("gemma") == "default"

    def test_reads_the_owner_window_from_ollama(self):
        _call("gemma4:e4b", _ps(("gemma4:e4b", 65536)))
        assert local_window.ollama_window("gemma4:e4b") == 65536
        assert local_window.ollama_num_ctx("gemma4:e4b") == 0          # never overridden
        assert local_window.source("gemma4:e4b") == "runtime"
        assert oracle_settings.context_window("gemma4:e4b") == 65536
        assert oracle_settings.ollama_request_options("gemma4:e4b")["options"] == {}

    def test_latest_tag_is_the_same_model(self):
        _call("gemma3", _ps(("gemma3:latest", 32768)))
        assert local_window.ollama_window("gemma3") == 32768

    def test_bare_install_gets_the_floor_without_flip_flop(self):
        _call("m", _ps(("m", 4096)))
        assert local_window.source("m") == "floor"
        assert local_window.ollama_num_ctx("m") == local_window.FLOOR
        assert local_window.ollama_window("m") == local_window.FLOOR
        _call("m", _ps(("m", local_window.FLOOR)))                       # loaded with what Oracle asked
        assert local_window.ollama_num_ctx("m") == local_window.FLOOR  # still asked: no reload ping-pong
        assert local_window.source("m") == "floor"

    def test_small_window_is_read_again_later(self, monkeypatch):
        _call("m", _ps(("m", 4096)))
        monkeypatch.setattr(local_window, "_RECHECK", 0)
        assert local_window.ollama_num_ctx("m") == 0                   # one call without num_ctx
        _call("m", _ps(("m", 65536)))                                  # the owner raised it in Ollama
        assert local_window.ollama_window("m") == 65536 and local_window.source("m") == "runtime"

    def test_forced_setting_wins(self, monkeypatch):
        _call("m", _ps(("m", 65536)))
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.NUM_CTX, 16384)
        assert local_window.ollama_window("m") == 16384
        assert local_window.ollama_num_ctx("m") == 16384
        assert local_window.source("m") == "setting"

    def test_window_loaded_by_a_previous_run_is_used_until_the_first_call(self):
        with patch("core.services.local_window.requests.get", return_value=_ps(("m", 32768))):
            local_window.refresh_ollama()
        assert local_window.ollama_window("m") == 32768
        assert local_window.ollama_window() == 32768                   # no model named: what Ollama has loaded
        assert local_window.ollama_num_ctx("m") == 0

    def test_unreachable_runtime_never_raises(self):
        with patch("core.services.local_window.requests.get", side_effect=OSError("down")):
            assert local_window.refresh_ollama() == {}
        assert local_window.ollama_window("m") == local_window.FLOOR


@pytest.mark.unit
class TestOpenAiCompatibleWindow:
    def _get(self, answers: dict):
        def fake(url, timeout=0):
            for suffix, payload in answers.items():
                if url.endswith(suffix):
                    r = MagicMock()
                    r.json.return_value = payload
                    return r
            raise OSError("404")
        return fake

    def test_lm_studio_loaded_context(self):
        answers = {"/api/v0/models": {"data": [{"id": "qwen", "state": "loaded", "loaded_context_length": 40960,
                                                "max_context_length": 131072}]}}
        with patch("core.services.local_window.requests.get", side_effect=self._get(answers)):
            assert local_window.openai_window("http://localhost:1234/v1", "qwen") == 40960

    def test_llama_server_props(self):
        answers = {"/props": {"default_generation_settings": {"n_ctx": 24576}}}
        with patch("core.services.local_window.requests.get", side_effect=self._get(answers)):
            assert local_window.openai_window("http://localhost:8080/v1", "any") == 24576

    def test_vllm_models(self):
        answers = {"/v1/models": {"data": [{"id": "big", "max_model_len": 100000}]}}
        with patch("core.services.local_window.requests.get", side_effect=self._get(answers)):
            assert local_window.openai_window("http://localhost:8000/v1", "big") == 100000

    def test_first_read_happens_on_a_machine_just_started(self):
        """The clock used for the cache starts near zero at boot: «never read» must not look «just read»."""
        answers = {"/props": {"n_ctx": 16384}}
        with patch("core.services.local_window.time.monotonic", return_value=5.0), \
             patch("core.services.local_window.threading.Thread") as thread, \
             patch("core.services.local_window.requests.get", side_effect=self._get(answers)):
            assert local_window.openai_window("http://localhost:8081/v1", "any") == 16384
            local_window._native["m"] = 32768          # already known: only the age of the last read decides
            local_window.note_call("m", 0)
            assert thread.called

    def test_silent_server_gives_zero_and_is_cached(self):
        with patch("core.services.local_window.requests.get", side_effect=OSError("down")) as get:
            assert local_window.openai_window("http://localhost:9/v1", "x") == 0
            calls = get.call_count
            assert local_window.openai_window("http://localhost:9/v1", "x") == 0
            assert get.call_count == calls


@pytest.mark.unit
class TestRuntimeInfoSource:
    def test_cloud_window_is_the_service_own(self):
        from agents.providers import runtime_info
        info = runtime_info("gemini", 8192)
        assert info["context_window"] == 1_048_576 and info["window_source"] == "provider"

    def test_ollama_window_says_where_it_comes_from(self):
        from agents.providers import runtime_info
        _call("m", _ps(("m", 65536)))
        info = runtime_info("ollama", 8192, "m")
        assert info["context_window"] == 65536 and info["window_source"] == "runtime"


@pytest.mark.unit
class TestSessionBreakdown:
    def test_parts_and_models_of_a_conversation(self):
        token = llm_stats._current_session.set("s1")
        try:
            llm_stats.note_breakdown({"system": 900, "tools": 3000, "history": 100, "message": 20, "results": 0})
            llm_stats.record("generic", "gemini", "flash", prompt_tokens=4000, output_tokens=50)
            llm_stats.record("classifier", "ollama", "gemma", prompt_tokens=300, output_tokens=5, estimated=True)
        finally:
            llm_stats._current_session.reset(token)
        usage = llm_stats.session_usage("s1")
        assert usage["calls"] == 2 and usage["breakdown"]["tools"] == 3000
        by = {r["provider"]: r for r in usage["by_model"]}
        assert by["gemini"]["estimated"] is False and by["gemini"]["input_tokens"] == 4000
        assert by["ollama"]["estimated"] is True and by["ollama"]["calls"] == 1

    def test_counter_window_follows_the_answering_model(self):
        assert al.TokenCounter(window=1_000_000).context_window == 1_000_000
        assert al.TokenCounter().context_window == local_window.FLOOR
        assert al.TokenCounter().from_chars(300) == 100


@pytest.mark.unit
class TestContextStats:
    def _engine(self, provider: str, model: str):
        from core.oracle_engine import OracleEngine
        eng = OracleEngine.__new__(OracleEngine)
        eng._hub = MagicMock()
        eng._hub.get_history.return_value = [{"role": "user", "content": "ciao"}]
        eng._mcp = MagicMock()
        eng._mcp.list_tools.return_value = [{"name": "t"}] * 3
        eng._load_preferences = lambda *_a, **_k: []
        eng._agents = MagicMock()
        eng._agents.generic.provider, eng._agents.generic.model_name = provider, model
        return eng

    def _turn(self, sid: str, provider: str, model: str, prompt_tokens: int, parts: dict):
        token = llm_stats._current_session.set(sid)
        try:
            llm_stats.note_breakdown(parts)
            llm_stats.record("generic", provider, model, prompt_tokens=prompt_tokens, estimated=provider == "ollama")
        finally:
            llm_stats._current_session.reset(token)

    def test_rows_add_up_to_the_measured_prompt_and_warn_over_the_window(self):
        _call("m", _ps(("m", 16384)))
        self._turn("s", "ollama", "m", 20000, {"system": 1000, "tools": 8000, "history": 500, "message": 100,
                                               "results": 400, "other": 0})
        stats = self._engine("ollama", "m").estimate_context_stats("s")
        assert stats["context_window"] == 16384 and stats["window_source"] == "runtime"
        assert stats["window_setting_key"] == oracle_settings.NUM_CTX
        assert stats["breakdown_measured"] is True and stats["over_window"] is True
        assert sum(r["tokens"] for r in stats["breakdown"]) == stats["context_used_tokens"] == 20000
        assert [r["id"] for r in stats["breakdown"]] == ["system", "tools", "history", "message", "results"]
        assert stats["session_usage"]["by_model"][0]["estimated"] is True

    def test_cloud_model_has_its_own_window_and_no_local_setting(self):
        self._turn("c", "gemini", "flash", 5000, {"system": 1000, "tools": 4000})
        stats = self._engine("gemini", "flash").estimate_context_stats("c")
        assert stats["context_window"] == 1_048_576 and stats["window_source"] == "provider"
        assert stats["window_setting_key"] == "" and stats["over_window"] is False

    def test_before_the_first_turn_it_is_a_rough_estimate(self):
        stats = self._engine("ollama", "m").estimate_context_stats("new")
        assert stats["breakdown_measured"] is False and stats["context_measured"] is False
        assert {r["id"] for r in stats["breakdown"]} == {"system", "tools", "history"}


@pytest.mark.unit
def test_final_frame_and_session_name_the_model_that_answered():
    import json
    from core.services import stream_emitter
    assert "model" not in json.loads(stream_emitter.emit_final("ciao"))
    assert json.loads(stream_emitter.emit_final("ciao", model="qwen3:14b"))["model"] == "qwen3:14b"
    assert llm_stats.last_model("nessuna") == ""

"""Chat modes (oracle.chat.mode) and per-conversation usage (dossier 2026-10-11-chat-modalita-contesto)."""
import pytest

from core.services import llm_stats, oracle_settings


@pytest.fixture(autouse=True)
def _clean_stats():
    llm_stats.reset()
    yield
    llm_stats.reset()


@pytest.mark.unit
class TestChatMode:
    def test_explicit_mode_wins(self, monkeypatch):
        monkeypatch.setattr(oracle_settings.settings, "user_values", lambda **kw: {oracle_settings.MODE: "quick"})
        assert oracle_settings.chat_mode("cot", client="webui", session="s") == "cot"

    def test_empty_follows_setting(self, monkeypatch):
        monkeypatch.setattr(oracle_settings.settings, "user_values", lambda **kw: {oracle_settings.MODE: "thinking"})
        assert oracle_settings.chat_mode("", client="telegram", session="s") == "thinking"

    def test_unknown_values_fall_back_to_auto(self, monkeypatch):
        monkeypatch.setattr(oracle_settings.settings, "user_values", lambda **kw: {oracle_settings.MODE: "bogus"})
        assert oracle_settings.chat_mode("nonsense") == "auto"

    def test_aliases(self):
        assert oracle_settings.normalize_mode("deep") == "cot"
        assert oracle_settings.normalize_mode("Rapida") == "quick"


@pytest.mark.unit
class TestSessionUsage:
    def test_bound_stream_counts_calls_for_its_session(self):
        def stream():
            llm_stats.record("generic", "ollama", "m", prompt_tokens=100, cached_tokens=40, output_tokens=5)
            yield "a"
            llm_stats.record_anthropic("generic", "claude_cli", "haiku",
                                       {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7},
                                       cost_usd=0.01)
            yield "b"

        assert list(llm_stats.bind_session("s1", stream())) == ["a", "b"]
        usage = llm_stats.session_usage("s1")
        assert usage["calls"] == 2
        assert usage["input_tokens"] == 200
        assert usage["cached_tokens"] == 130
        assert usage["output_tokens"] == 12
        assert usage["last_prompt_tokens"] == 100
        assert usage["cost_usd"] == pytest.approx(0.01)

    def test_unbound_calls_are_not_counted_for_a_session(self):
        llm_stats.record("generic", "ollama", "m", prompt_tokens=10)
        assert llm_stats.session_usage("s1") == {}

    def test_gemini_usage_metadata(self):
        class Meta:
            prompt_token_count, cached_content_token_count = 500, 100
            candidates_token_count, thoughts_token_count = 20, 30

        class Resp:
            usage_metadata = Meta()

        row = llm_stats.record_gemini("generic", "gemini-2.5-flash", Resp())
        assert row["prompt_tokens"] == 500 and row["cached_tokens"] == 100 and row["output_tokens"] == 50


@pytest.mark.unit
def test_runtime_info_window_and_billing():
    from agents.providers import runtime_info

    assert runtime_info("ollama", 8192)["context_window"] == 8192
    assert runtime_info("gemini", 8192)["context_window"] == 1_048_576
    claude = runtime_info("claude_cli", 8192)
    assert claude["context_window"] == 200_000 and "Abbonamento" in claude["billing"]

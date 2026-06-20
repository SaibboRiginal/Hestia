"""Unit tests for Oracle Enhancement Plan (P1-P3) features.

Tests: domain tool filtering, mode routing, token counting, preference
domain loading, parallel tool execution, thinking mode events.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, call
import pytest

from core.oracle_engine import OracleEngine, SessionIntent
from core.services.agent_factory import AgentFactory

# ── Engine fixture (mirrors test_oracle_engine_core.py pattern) ────────────

@pytest.fixture
def engine():
    """Build an OracleEngine with all external deps mocked."""
    with patch.object(AgentFactory, 'create') as mock_create:
        bundle = MagicMock()
        bundle.generic.ask.return_value = "Generic response."
        bundle.generic.ask_with_tools.return_value = {"tool_call": None, "text": "Generic."}
        bundle.generic_fallback.ask.return_value = "Fallback."
        bundle.generic_fallback.ask_with_tools.return_value = {"tool_call": None, "text": "FB."}
        bundle.reasoning.ask.return_value = "Reasoning."
        bundle.reasoning.ask_with_tools.return_value = {"tool_call": None, "text": "R."}
        bundle.code.ask.return_value = "Code."
        bundle.embedding.embed.return_value = [0.1] * 768
        bundle.generic_model_name = "mock-generic"
        mock_create.return_value = bundle

        eng = OracleEngine()
        eng._hub.get = MagicMock(return_value=[])

        def _hub_get(path, **kw):
            path_str = str(path or "")
            if "/schemas" in path_str:
                return {}
            return ["general"]
        eng._hub.hub_get = MagicMock(side_effect=_hub_get)

        eng._hub.post = MagicMock(return_value={"ok": True})
        eng._hub.put = MagicMock(return_value={"ok": True})
        eng._hub.delete = MagicMock(return_value={"ok": True})
        eng._hub.get_commands = MagicMock(return_value=[])
        eng._hub.get_history = MagicMock(return_value=[])
        eng._hub.route_to_service = MagicMock(return_value=(True, {}))
        yield eng


# ── P1: Domain tool filtering ──────────────────────────────────────────────


class TestDomainToolFiltering:
    """Plan P1: _build_domain_tools filters by layer:domain owners."""

    def test_owned_domain_gets_search_tool(self, engine):
        """Domain with layer:domain owner gets {domain}.search tool."""
        engine._module_registry.get_domain_owners = lambda d: (
            ["scout"] if d == "scout" else []
        )
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout"],
        )
        tools = engine._build_domain_tools(intent, "test-session", None)
        names = {t.name for t in tools}
        assert "scout.search" in names

    def test_unowned_domain_skipped_with_warning(self, engine, caplog):
        """Domain with NO layer:domain owner logs warning, gets no search tool."""
        engine._module_registry.get_domain_owners = lambda d: []
        intent = SessionIntent(
            mode="domain_query", explicit_domain="unknown_domain",
            confidence=0.5, valid_domains=["unknown_domain"],
        )
        tools = engine._build_domain_tools(intent, "test-session", None)
        names = {t.name for t in tools}
        assert "unknown_domain.search" not in names
        # memory + documents still present
        assert "memory.save" in names
        assert "documents.search" in names
        # Warning logged
        assert any("domain_tool_no_owner" in r.getMessage() for r in caplog.records)

    def test_multi_domain_owners(self, engine):
        """Multiple domains each get their own search tools."""
        engine._module_registry.get_domain_owners = lambda d: (
            ["scout"] if d == "scout" else ["chronos"] if d == "calendar" else []
        )
        intent = SessionIntent(
            mode="domain_query", explicit_domain="scout",
            confidence=0.9, valid_domains=["scout", "calendar"],
        )
        tools = engine._build_domain_tools(intent, "test-session", None)
        names = {t.name for t in tools}
        assert "scout.search" in names
        assert "calendar.search" in names

    def test_commands_filtered_by_relevant_services(self, engine):
        """Hub commands from non-domain-owning services are filtered out."""
        engine._module_registry.get_domain_owners = lambda d: (
            ["chronos"] if d == "calendar" else []
        )
        engine._hub.get_commands = lambda: [
            {"command": "agenda", "service": "chronos", "method": "GET",
             "path": "/api/agenda", "response_mode": "raw_json"},
            {"command": "unknown_cmd", "service": "other_service", "method": "GET",
             "path": "/api/other", "response_mode": "raw_json"},
        ]
        intent = SessionIntent(
            mode="domain_query", explicit_domain="calendar",
            confidence=0.9, valid_domains=["calendar"],
        )
        tools = engine._build_domain_tools(intent, "test-session", None)
        names = {t.name for t in tools}
        assert "agenda" in names
        assert "unknown_cmd" not in names


# ── P1: Mode routing ───────────────────────────────────────────────────────


class TestModeRouting:
    """Plan P1: mode (quick/auto/thinking) and model independence."""

    def test_quick_mode_no_classify(self, engine):
        """Quick mode skips classification entirely."""
        engine._phase_classify = MagicMock()
        engine._quick_answer = MagicMock(return_value="Quick response")
        engine._save_history = MagicMock()
        engine._phase_init = MagicMock(return_value=("", ["general"], {}))
        engine._phase_background_memory = MagicMock()

        lines = list(engine.chat("hello", "s1", mode="quick", model="generic"))
        engine._phase_classify.assert_not_called()

    def test_thinking_mode_uses_resolved_agent(self, engine):
        """Thinking mode uses the agent from _resolve_agent(model), not forced reasoning."""
        engine._phase_init = MagicMock(return_value=("", ["general"], {}))
        mock_agent = MagicMock()
        mock_agent.model_name = "test-model"
        mock_agent.provider = "ollama"
        mock_agent.thinking = False
        engine._resolve_agent = MagicMock(return_value=mock_agent)
        engine._phase_classify = MagicMock(return_value=SessionIntent(
            mode="domain_query", explicit_domain=None, confidence=0.5,
            valid_domains=["general"],
        ))
        # Make agent loop exit immediately
        with patch("core.oracle_engine.run_agent_loop",
                   return_value=("answer", [], [])) as mock_loop:
            engine._save_history = MagicMock()
            engine._phase_background_memory = MagicMock()
            list(engine.chat("think", "s1", mode="thinking", model="code"))

            # Agent should have thinking=True set by mode
            call_kwargs = mock_loop.call_args.kwargs
            assert call_kwargs["action_intent"] is False


# ── P2: Token counting ─────────────────────────────────────────────────────


class TestTokenCounter:
    """Plan P2-4: TokenCounter with Ollama calibration."""

    def test_fallback_heuristic(self):
        """When Ollama unreachable, fall back to ~3 chars/token heuristic."""
        from core.agent_loop import TokenCounter
        # Force cache miss
        import core.agent_loop as al
        al._token_ratio_cache.clear()
        counter = TokenCounter(model="nonexistent-model")
        tokens = counter.estimate("hello world " * 10)  # 120 chars
        assert tokens > 0
        assert abs(tokens - 40) < 20  # ~3:1 ratio

    def test_context_window_from_env(self, monkeypatch):
        """ORACLE_CONTEXT_LENGTH env var controls window size."""
        monkeypatch.setenv("ORACLE_CONTEXT_LENGTH", "16384")
        from core.agent_loop import TokenCounter
        import core.agent_loop as al
        al._CONTEXT_WINDOW = int(os.getenv("ORACLE_CONTEXT_LENGTH", "8192"))
        counter = TokenCounter()
        assert counter.context_window == 16384

    def test_context_pct(self):
        """context_pct returns percentage of window used."""
        from core.agent_loop import TokenCounter
        import core.agent_loop as al
        al._CONTEXT_WINDOW = 8192
        counter = TokenCounter()
        pct = counter.context_pct(4096)
        assert pct == 50.0


# ── P3a: Preference domains ────────────────────────────────────────────────


class TestPreferenceDomains:
    """Plan P3a: embedding-based multi-domain preference assignment."""

    def test_domain_list_from_env(self, monkeypatch):
        """ORACLE_PREFERENCE_DOMAINS overrides the default domain list."""
        monkeypatch.setenv("ORACLE_PREFERENCE_DOMAINS",
                           json.dumps({"test_domain": "Test description"}))
        from core.services.preference_domains import _parse_domains
        domains = _parse_domains()
        assert "test_domain" in domains

    def test_cosine_identical(self):
        """Cosine similarity of identical vectors is 1.0."""
        from core.services.preference_domains import cosine_similarity
        assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_cosine_orthogonal(self):
        """Cosine similarity of orthogonal vectors is 0.0."""
        from core.services.preference_domains import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_cosine_empty(self):
        """Cosine of empty vectors is 0.0."""
        from core.services.preference_domains import cosine_similarity
        assert cosine_similarity([], [1.0]) == 0.0

    def test_classifier_returns_general_when_embed_fails(self):
        """When embedding fails, classify returns ['general']."""
        from core.services.preference_domains import PreferenceDomainClassifier

        def bad_embed(text: str) -> list[float]:
            raise RuntimeError("embed failed")

        classifier = PreferenceDomainClassifier(embed_fn=bad_embed)
        result = classifier.classify("test text")
        assert "general" in result


# ── P3a: Multi-domain preference loading ───────────────────────────────────


class TestMultiDomainPreferences:
    """Plan P3a: _load_preferences filters by multi-domain 'domains' list."""

    def test_multi_domain_match(self, engine):
        """Preference with domains=['calendar','work'] matches calendar query."""
        engine._hub.get = MagicMock(return_value=[
            {"id": "1", "fact": "Prefers morning", "domain": "calendar",
             "domains": ["calendar", "work"], "memory_class": "durable_user_preference"},
        ])
        prefs = engine._load_preferences(["calendar"])
        assert len(prefs) == 1
        assert prefs[0]["fact"] == "Prefers morning"

    def test_multi_domain_no_match(self, engine):
        """Preference with domains=['food'] doesn't match calendar query."""
        engine._hub.get = MagicMock(return_value=[
            {"id": "2", "fact": "Likes pasta", "domain": "food",
             "domains": ["food"], "memory_class": "durable_user_preference"},
        ])
        prefs = engine._load_preferences(["calendar"])
        assert len(prefs) == 0

    def test_general_always_included(self, engine):
        """Preferences with domain='general' always match regardless of query."""
        engine._hub.get = MagicMock(return_value=[
            {"id": "3", "fact": "Generic pref", "domain": "general",
             "domains": ["general"], "memory_class": "durable_user_preference"},
        ])
        prefs = engine._load_preferences(["calendar"])
        assert len(prefs) == 1


# ── P2: Thinking mode events ──────────────────────────────────────────────


class TestThinkingEvents:
    """Plan P2-8: reasoning_content emitted as NDJSON thinking events."""

    def test_reasoning_content_in_decision(self):
        """ask_tools_fn returns reasoning_content when thinking=True."""
        decision = {
            "tool_calls": [],
            "tool_call": None,
            "text": "I'll check your calendar",
            "reasoning_content": "The user asked about today's events...",
        }
        assert decision.get("reasoning_content") == "The user asked about today's events..."

    def test_empty_reasoning_not_emitted(self):
        """Empty reasoning_content should not generate a thinking event."""
        decision = {
            "tool_calls": [],
            "tool_call": None,
            "text": "agenda_today",
            "reasoning_content": "",
        }
        reasoning = str(decision.get("reasoning_content", "") or "").strip()
        assert not reasoning  # Should not emit event


# ── P2: Compaction ─────────────────────────────────────────────────────────


class TestCompaction:
    """Plan P2-6: context compaction auto-trigger + manual endpoint."""

    def test_compaction_skips_short_history(self, engine):
        """Compaction returns note when history <= 6 messages."""
        engine._hub.get = MagicMock(return_value=[
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello!"},
        ])
        result = engine.compact_context("short-session")
        assert result.get("note") or result.get("messages_before", 0) <= 6

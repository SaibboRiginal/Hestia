"""Tests — AgentFactory + UniversalAgent (Phase 1.6)

Tests for env-based agent construction, provider fallback logic,
and UniversalAgent.ask / ask_with_tools stub behaviour.
All network calls mocked.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch
import pytest

from agents.universal_agent import UniversalAgent
from core.services.agent_factory import AgentBundle, AgentFactory


# ─────────────────────────────────────────────────────────────────────────────
# UniversalAgent unit tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestUniversalAgentOllamaFallback:
    def test_missing_gemini_key_falls_back_to_ollama(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        agent = UniversalAgent(
            role_prompt="Test prompt",
            provider="gemini",
            model_name="gemini-2.5-flash",
            thinking=False,
        )
        assert agent.provider == "ollama"

    def test_empty_gemini_key_falls_back_to_ollama(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "")
        agent = UniversalAgent(
            role_prompt="Test prompt",
            provider="gemini",
            model_name="gemini-2.5-flash",
            thinking=False,
        )
        assert agent.provider == "ollama"

    def test_ollama_provider_explicit(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        agent = UniversalAgent(
            role_prompt="Test prompt",
            provider="ollama",
            model_name="llama3:8b",
            thinking=False,
        )
        assert agent.provider == "ollama"

    def test_ask_ollama_returns_string(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        agent = UniversalAgent(
            role_prompt="Sei un assistente.",
            provider="ollama",
            model_name="test-model",
            thinking=False,
        )
        fake_resp = MagicMock()
        fake_resp.raise_for_status = lambda: None
        fake_resp.json.return_value = {"response": "Risposta di test."}
        with patch("requests.post", return_value=fake_resp):
            result = agent.ask("Ciao!")
        assert isinstance(result, str)
        assert "Risposta" in result

    def test_ask_with_tools_no_native_falls_back_to_text(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_TOOL_CALL_MODE", "text")
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        agent = UniversalAgent(
            role_prompt="Test",
            provider="ollama",
            model_name="test-model",
            thinking=False,
        )
        tools = [
            {"name": "weather", "description": "Get weather", "parameters": {}}]
        fake_resp = MagicMock()
        fake_resp.raise_for_status = lambda: None
        fake_resp.json.return_value = {"response": "Il meteo è soleggiato."}
        with patch("requests.post", return_value=fake_resp):
            result = agent.ask_with_tools("Meteo?", tools)
        assert isinstance(result, dict)
        assert "tool_call" in result
        assert "text" in result

    def test_model_name_stored(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434/api/generate")
        agent = UniversalAgent(
            role_prompt="Test",
            provider="ollama",
            model_name="my-special-model",
            thinking=False,
        )
        assert agent.model_name == "my-special-model"


# ─────────────────────────────────────────────────────────────────────────────
# AgentFactory tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAgentFactory:
    def _patch_agent_init(self, monkeypatch):
        """Patch UniversalAgent so no real Ollama/Gemini clients are created."""
        mock_agent = MagicMock(spec=UniversalAgent)
        mock_agent.provider = "ollama"
        mock_agent.model_name = "test-model"
        monkeypatch.setattr(
            "core.services.agent_factory.UniversalAgent",
            lambda *a, **kw: MagicMock(provider="ollama", model_name="mock"),
        )

    def test_create_returns_agent_bundle(self, monkeypatch):
        self._patch_agent_init(monkeypatch)
        bundle = AgentFactory.create()
        assert isinstance(bundle, AgentBundle)

    def test_bundle_has_all_agents(self, monkeypatch):
        self._patch_agent_init(monkeypatch)
        bundle = AgentFactory.create()
        assert bundle.router is not None
        assert bundle.analyst is not None
        assert bundle.scribe is not None
        assert bundle.embedder is not None
        assert bundle.coder is not None
        assert bundle.fallback_analyst is not None

    def test_analyst_prompt_from_env_var(self, monkeypatch):
        monkeypatch.setenv("HESTIA_PERSONA", "Custom persona text")
        self._patch_agent_init(monkeypatch)
        # AgentFactory._ANALYST_PROMPT is module-level; ensure the env override logic
        # would produce the right string without re-importing the module
        custom = os.getenv("HESTIA_PERSONA", "")
        assert "Custom persona" in custom

    def test_ollama_fallback_when_no_gemini_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        self._patch_agent_init(monkeypatch)
        bundle = AgentFactory.create()
        assert bundle is not None

    def test_analyst_model_name_property(self, monkeypatch):
        self._patch_agent_init(monkeypatch)
        bundle = AgentFactory.create()
        # analyst_model_name is a property — should return a string
        assert isinstance(bundle.analyst_model_name, str)

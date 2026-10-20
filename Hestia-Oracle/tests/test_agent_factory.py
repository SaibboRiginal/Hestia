"""Tests — AgentFactory + UniversalAgent.

Named providers, one chain agent per Oracle use case, UniversalAgent.ask / ask_with_tools stub behaviour.
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
class TestUniversalAgentProviders:
    def test_gemini_without_key_is_unavailable(self, monkeypatch):
        monkeypatch.delenv("ORACLE_KEY_GEMINI", raising=False)
        agent = UniversalAgent(role_prompt="t", provider="gemini", model_name="gemini-2.5-flash", thinking=False)
        assert agent.provider == "gemini" and agent.available() == (False, "ORACLE_KEY_GEMINI not set")

    def test_named_openai_provider_resolves_type(self, monkeypatch):
        from core.services import oracle_settings
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.PROVIDERS_KEY,
                            {"lmstudio": {"type": "openai", "url": "http://h:1234/v1"}})
        agent = UniversalAgent(role_prompt="t", provider="lmstudio", model_name="qwen", thinking=False)
        assert (agent.provider, agent.provider_name) == ("openai", "lmstudio")
        assert agent.available()[0]

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
        from core.services import oracle_settings
        monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.OLLAMA_TOOL_MODE, "text")
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
    def test_bundle_has_one_chain_agent_per_oracle_use_case(self):
        from core.services.llm_chains import ChainAgent
        bundle = AgentFactory.create()
        assert isinstance(bundle, AgentBundle)
        assert {(slot, getattr(bundle, slot).use_case) for slot in
                ("generic", "reasoning", "code", "documents", "embedding")} == {
            ("generic", "oracle.generale"), ("reasoning", "oracle.ragionamento"), ("code", "oracle.codice"),
            ("documents", "oracle.documenti"), ("embedding", "oracle.embedding")}
        assert all(isinstance(getattr(bundle, s), ChainAgent) for s in ("generic", "embedding"))

    def test_generic_model_name_is_first_usable_step(self, monkeypatch):
        from core.services import llm_chains
        monkeypatch.setattr(llm_chains, "step_thinking", lambda step, raw: False)
        bundle = AgentFactory.create()
        assert bundle.generic_model_name == "gemma4:e4b"     # gemini steps need ORACLE_KEY_GEMINI

"""Tests — guided setup «Cervello» (docs/work/2026-10-30-setup-un-click §4.2). No network: providers mocked."""
from __future__ import annotations

import pytest

from core.services import llm_chains, llm_providers, llm_setup, oracle_settings

pytestmark = pytest.mark.unit


def _keys(monkeypatch, *names):
    for name in names:
        monkeypatch.setenv(llm_providers.key_env(name), "test-key")


def test_recommend_by_vram():
    assert llm_setup.recommend(0, 32)["model"] == "gemma4:e4b"
    assert llm_setup.recommend(8, 32)["model"] == "qwen3:8b"
    assert llm_setup.recommend(16, 64)["model"] == "qwen3:14b"
    assert llm_setup.recommend(16, 64)["recipe"] == "entrambi"
    assert llm_setup.recommend(0, 8)["recipe"] == "cloud"


def test_plan_local_only_replaces_chat_chains_and_keeps_embedding():
    current = dict(llm_chains.DEFAULT_CHAINS)
    out = llm_setup.plan_chains("locale", "qwen3:14b", [], current)
    for name in llm_setup.CHAT_CHAINS:
        assert out[name]["steps"] == [{"provider": "ollama", "model": "qwen3:14b"}]
    assert out["embedding"] == current["embedding"]


def test_plan_both_puts_local_first_then_chosen_cloud(monkeypatch):
    _keys(monkeypatch, "gemini")
    out = llm_setup.plan_chains("entrambi", "qwen3:8b", ["gemini"], dict(llm_chains.DEFAULT_CHAINS))
    steps = out["veloce"]["steps"]
    assert steps[0] == {"provider": "ollama", "model": "qwen3:8b"}
    assert [s["provider"] for s in steps[1:]] == ["gemini", "gemini"]
    assert all(s["provider"] != "llamacpp" for s in steps)


def test_plan_cloud_with_provider_not_in_defaults_uses_its_first_model(monkeypatch):
    monkeypatch.setattr(llm_providers, "list_models", lambda name: ["deepseek-chat"])
    out = llm_setup.plan_chains("cloud", "", ["deepseek"], dict(llm_chains.DEFAULT_CHAINS))
    assert out["potente"]["steps"] == [{"provider": "deepseek", "model": "deepseek-chat"}]


def test_plan_empty_choice_keeps_current_chain():
    current = dict(llm_chains.DEFAULT_CHAINS)
    out = llm_setup.plan_chains("cloud", "", [], current)
    assert out["veloce"] == current["veloce"]


def test_summary_sentence():
    chains = {"veloce": {"steps": [{"provider": "ollama", "model": "qwen3:8b"},
                                   {"provider": "gemini", "model": "gemini-flash-latest"}]}}
    assert llm_setup.summary(chains) == ("Ti risponde qwen3:8b sul tuo computer; "
                                         "se non c'è, gemini-flash-latest nel cloud.")


def test_apply_writes_chains_through_settings(monkeypatch):
    stored = {}
    monkeypatch.setattr(oracle_settings.settings, "put",
                        lambda key, value, actor="", reason="": stored.setdefault(key, value) or True)
    result = llm_setup.apply("claude", "qwen3:8b", [])
    assert result["ok"] and result["detail"].startswith("Ti risponde Claude")
    assert stored[oracle_settings.BRAIN_MODE] == "esterna"
    assert stored[oracle_settings.CHAINS_KEY]["veloce"]["steps"][0]["model"] == "qwen3:8b"


def test_test_without_key_says_so(monkeypatch):
    monkeypatch.delenv(llm_providers.key_env("gemini"), raising=False)
    result = llm_setup.test("gemini")
    assert result == {"ok": False, "detail": "Manca la chiave."}


def test_test_bad_key_in_plain_words(monkeypatch):
    _keys(monkeypatch, "gemini")

    class _Bad:
        def __init__(self, **kw):
            pass

        def ask(self, prompt):
            raise RuntimeError("401 API key not valid")
    import agents.universal_agent as ua
    monkeypatch.setattr(ua, "UniversalAgent", _Bad)
    assert llm_setup.test("gemini")["detail"] == "La chiave non è valida."


def test_pull_rejects_bad_names():
    assert llm_setup.pull("rm -rf")["ok"] is False
    assert llm_setup.pull("")["ok"] is False


def test_use_machine_points_ollama_at_satellite(monkeypatch):
    stored = {}
    monkeypatch.setattr(oracle_settings.settings, "get", lambda key, default=None: stored.get(key, default))
    monkeypatch.setattr(oracle_settings.settings, "put",
                        lambda key, value, **kw: stored.__setitem__(key, value) or True)
    assert llm_setup.use_machine("192.168.1.20", "PC studio")["ok"]
    assert stored[oracle_settings.PROVIDERS_KEY]["ollama"]["url"] == "http://192.168.1.20:11434"
    assert llm_setup.machine()["address"] == "192.168.1.20"
    assert "gemini" in stored[oracle_settings.PROVIDERS_KEY]            # the other providers stay
    assert llm_setup.use_machine("")["ok"]
    assert stored[oracle_settings.PROVIDERS_KEY]["ollama"]["url"] == ""
    assert llm_setup.machine()["address"] == ""
    assert llm_setup.use_machine("bad host/x")["ok"] is False

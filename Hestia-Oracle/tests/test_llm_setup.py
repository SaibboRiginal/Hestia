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
    import requests

    class _Resp:
        status_code, ok = 400, False
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
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


def test_local_models_lists_ollama_chat_models_with_fit_warning(monkeypatch):
    """The setup shows what is already in Ollama (not a hand list): embedding models out, too-big ones flagged."""
    class _Resp:
        ok = True
        def raise_for_status(self): pass
        def json(self):
            return {"models": [
                {"name": "qwen3:14b", "size": 9.3e9, "details": {"family": "qwen3", "parameter_size": "14.8B"}},
                {"name": "llama3.3:70b", "size": 42e9, "details": {"family": "llama"}},
                {"name": "qwen3-embedding:0.6b", "size": 0.6e9, "details": {"family": "qwen3"}},
                {"name": "nomic-bert", "size": 0.3e9, "details": {"family": "nomic-bert", "families": ["nomic-bert"]}},
                {"name": "gemma4:e4b", "size": 3.3e9, "details": {}}]}
    import requests
    monkeypatch.setattr(llm_providers, "get", lambda name: {"type": "ollama"})
    monkeypatch.setattr(llm_providers, "url", lambda name: "http://ollama")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    rows = llm_setup.local_models(16)
    assert [r["model"] for r in rows] == ["qwen3:14b", "gemma4:e4b", "llama3.3:70b"]
    assert [r["fits"] for r in rows] == [True, True, False]
    assert rows[0]["params"] == "14.8B"
    assert all(r["fits"] for r in llm_setup.local_models(0))      # card unknown: no warning


class _ListResp:
    status_code, ok = 200, True

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def test_test_reads_the_model_list_and_spends_no_tokens(monkeypatch):
    """Marko 2026-11-06: «Prova» must cost (almost) nothing and never ask the key twice: the list is the check."""
    _keys(monkeypatch, "gemini")
    import requests
    import agents.universal_agent as ua
    monkeypatch.setattr(ua, "UniversalAgent", lambda **kw: pytest.fail("no model call when the list can be read"))
    monkeypatch.setattr(requests, "get", lambda *a, **k: _ListResp({"models": [
        {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-3-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-embedding-002", "supportedGenerationMethods": ["embedContent"]}]}))
    result = llm_setup.test("gemini")
    assert result["ok"] and result["models"] == ["gemini-3-flash", "gemini-3-flash-lite"]
    assert result["model"] == "gemini-3-flash-lite"            # the default alias is gone: the cheapest-looking one
    assert llm_setup.test("gemini", "gemini-3-flash")["model"] == "gemini-3-flash"


def test_test_without_a_list_makes_one_tiny_call(monkeypatch):
    monkeypatch.setattr(llm_setup, "_list_checked", lambda provider: (None, ""))
    import agents.universal_agent as ua

    class _Agent:
        def __init__(self, **kw):
            pass

        def ask(self, prompt):
            return "ok"
    monkeypatch.setattr(ua, "UniversalAgent", _Agent)
    monkeypatch.setattr(llm_providers, "available", lambda name: (True, "ok"))
    result = llm_setup.test("deepseek", "deepseek-chat")
    assert result["ok"] and result["model"] == "deepseek-chat"


def test_pull_skips_a_model_already_in_ollama(monkeypatch):
    """A model made from a Modelfile is on no registry: «già presente», not «non esiste su Ollama»."""
    monkeypatch.setattr(llm_providers, "list_models", lambda name: ["gemma-4-26B-A4B-it-UD-IQ4_NL:latest"])
    out = llm_setup.pull("gemma-4-26B-A4B-it-UD-IQ4_NL:latest")
    assert out["ok"] and out["already"] and out["state"] == "fatto"


def test_is_local_by_type_then_address(monkeypatch):
    provs = {"ollama": {"type": "ollama", "url": ""},
             "lmstudio": {"type": "openai", "url": "http://host.docker.internal:1234/v1"},
             "casa": {"type": "openai", "url": "http://192.168.1.20:8000/v1"},
             "deepseek": {"type": "openai", "url": "https://api.deepseek.com/v1"},
             "gemini": {"type": "gemini", "url": ""}}
    monkeypatch.setattr(oracle_settings.settings, "get", lambda key, default=None: provs)
    assert [n for n in provs if llm_providers.is_local(n)] == ["ollama", "lmstudio", "casa"]


def test_runtimes_finds_lm_studio_and_lists_its_models(monkeypatch):
    monkeypatch.setattr(llm_setup, "_ollama_up", lambda: False)
    monkeypatch.setattr(llm_setup, "_host", lambda: "host.docker.internal")
    monkeypatch.setattr(llm_providers, "providers", lambda: {})
    answers = {"http://host.docker.internal:1234/v1": ["qwen3-14b", "text-embedding-nomic-embed-text-v1.5"]}
    monkeypatch.setattr(llm_setup, "_probe_openai", lambda base: answers.get(base))
    rows = {r["name"]: r for r in llm_setup.runtimes(16)}
    assert rows["ollama"]["found"] is False
    assert rows["lmstudio"]["found"] is True and not rows["lmstudio"]["configured"]
    assert [m["model"] for m in rows["lmstudio"]["models"]] == ["qwen3-14b"]
    assert rows["lmstudio"]["embed"] == ["text-embedding-nomic-embed-text-v1.5"]
    assert rows["jan"]["found"] is False and rows["vllm"]["models"] == []


def test_ensure_runtime_adds_the_program_as_a_block(monkeypatch):
    stored = {oracle_settings.PROVIDERS_KEY: dict(llm_providers.DEFAULT_PROVIDERS)}
    monkeypatch.setattr(oracle_settings.settings, "get", lambda key, default=None: stored.get(key, default))
    monkeypatch.setattr(oracle_settings.settings, "put", lambda key, value, **kw: stored.__setitem__(key, value) or True)
    monkeypatch.setattr(llm_setup, "_host", lambda: "host.docker.internal")
    assert llm_setup.ensure_runtime("lmstudio")
    block = stored[oracle_settings.PROVIDERS_KEY]["lmstudio"]
    assert block == {"type": "openai", "label": "LM Studio (locale)", "url": "http://host.docker.internal:1234/v1"}
    assert "gemini" in stored[oracle_settings.PROVIDERS_KEY]
    assert llm_setup.ensure_runtime("nessuno") is False


def test_plan_uses_the_chosen_program_cloud_models_and_embedding(monkeypatch):
    _keys(monkeypatch, "gemini")
    monkeypatch.setattr(llm_providers, "is_local", lambda name: name in ("ollama", "llamacpp", "lmstudio"))
    current = dict(llm_chains.DEFAULT_CHAINS)
    out = llm_setup.plan_chains("entrambi", "qwen3-14b", ["gemini"], current, local_provider="lmstudio",
                                cloud_models={"gemini": "gemini-3-flash"},
                                embedding={"provider": "ollama", "model": "qwen3-embedding:0.6b"})
    assert out["veloce"]["steps"] == [{"provider": "lmstudio", "model": "qwen3-14b"},
                                      {"provider": "gemini", "model": "gemini-3-flash"}]
    assert out["cloud"]["steps"] == [{"provider": "gemini", "model": "gemini-3-flash"}]
    assert out["embedding"] == current["embedding"]                       # same model: memory not re-indexed
    out = llm_setup.plan_chains("locale", "qwen3-14b", [], current, local_provider="lmstudio",
                                embedding={"provider": "lmstudio", "model": "text-embedding-nomic"})
    assert out["embedding"]["steps"] == [{"provider": "lmstudio", "model": "text-embedding-nomic"}]


def test_apply_replaces_a_retired_default_with_a_listed_model(monkeypatch):
    """Key already saved, no «Prova»: the chain must not start with an alias Google no longer lists."""
    _keys(monkeypatch, "gemini")
    stored = {}
    monkeypatch.setattr(oracle_settings.settings, "put", lambda key, value, **kw: stored.__setitem__(key, value) or True)
    monkeypatch.setattr(llm_providers, "list_models", lambda name: ["gemini-flash-latest", "gemini-3-flash"])
    assert llm_setup.apply("cloud", "", ["gemini"])["ok"]
    steps = stored[oracle_settings.CHAINS_KEY]["veloce"]["steps"]
    assert {s["model"] for s in steps} <= {"gemini-flash-latest", "gemini-3-flash"}


def test_key_ok_preselects_more_than_one_model_in_order(monkeypatch):
    """Marko 2026-11-06 (fourth time): a working key must not stop on «pick a model»: two models are preselected,
    the second as the fallback, and speech/picture models are never among them."""
    _keys(monkeypatch, "gemini")
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _ListResp({"models": [
        {"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]}
        for m in ("gemini-2.5-flash-preview-tts", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-flash-lite-latest")]}))
    result = llm_setup.test("gemini")
    assert result["recommended"] == ["gemini-flash-lite-latest", "gemini-2.5-flash"]


def test_plan_puts_every_chosen_model_of_a_service_in_order(monkeypatch):
    _keys(monkeypatch, "gemini")
    monkeypatch.setattr(llm_providers, "is_local", lambda name: name == "ollama")
    out = llm_setup.plan_chains("entrambi", "qwen3:8b", ["gemini"], dict(llm_chains.DEFAULT_CHAINS),
                                cloud_models={"gemini": ["gemini-a", "gemini-b", "gemini-a"]})
    assert out["veloce"]["steps"] == [{"provider": "ollama", "model": "qwen3:8b"},
                                      {"provider": "gemini", "model": "gemini-a"},
                                      {"provider": "gemini", "model": "gemini-b"}]

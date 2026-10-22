"""Tests — named providers, model chains, use cases, migration (dossier 2026-10-19-oracle-a-blocchi).
All network calls mocked."""
from __future__ import annotations

import time
from types import SimpleNamespace as NS

import pytest

from core.services import llm_chains, llm_migration, llm_providers, oracle_settings


def _set(monkeypatch, key, value):
    monkeypatch.setitem(oracle_settings.settings._effective, key, value)


class _Agent:
    """Stand-in UniversalAgent: behaviour per model name."""
    plan: dict = {}
    asked: list = []

    def __init__(self, role_prompt="", provider="", model_name="", thinking=False, label=""):
        self.provider_name, self.model_name, self.thinking = provider, model_name, thinking

    def _run(self):
        _Agent.asked.append(self.model_name)
        outcome = _Agent.plan.get(self.model_name, "ok")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def ask(self, prompt, thinking=None):
        return self._run()

    def embed(self, text):
        self._run()
        return [0.1]

    def ask_stream(self, prompt):
        outcome = _Agent.plan.get(self.model_name, "ok")
        _Agent.asked.append(self.model_name)
        if outcome == "mid":
            yield "par"
            raise RuntimeError("cut")
        if isinstance(outcome, Exception):
            raise outcome
        yield from ("a", "b")


@pytest.fixture
def fake_agents(monkeypatch):
    _Agent.plan, _Agent.asked = {}, []
    monkeypatch.setattr("agents.universal_agent.UniversalAgent", _Agent)
    monkeypatch.setattr(llm_chains, "step_thinking", lambda step, raw: False)
    monkeypatch.setenv("ORACLE_KEY_GEMINI", "k")
    return _Agent


@pytest.mark.unit
class TestProviders:
    def test_key_env_name(self):
        assert llm_providers.key_env("claude-api") == "ORACLE_KEY_CLAUDE_API"
        assert llm_providers.key_env("deepseek") == "ORACLE_KEY_DEEPSEEK"

    def test_defaults_and_availability(self, monkeypatch):
        monkeypatch.delenv("ORACLE_KEY_GEMINI", raising=False)
        names = set(llm_providers.providers())
        assert {"ollama", "llamacpp", "gemini", "deepseek", "claude-api", "claude"} <= names
        assert llm_providers.available("ollama")[0]
        assert not llm_providers.available("gemini")[0]
        assert not llm_providers.available("claude-api")[0]
        monkeypatch.setenv("ORACLE_KEY_CLAUDE_API", "x")
        assert llm_providers.available("claude-api")[0]

    def test_unknown_type_is_dropped(self, monkeypatch):
        _set(monkeypatch, oracle_settings.PROVIDERS_KEY, {"x": {"type": "nope"}, "o": {"type": "ollama"}})
        assert list(llm_providers.providers()) == ["o"]

    def test_public_view_never_contains_keys(self, monkeypatch):
        monkeypatch.setenv("ORACLE_KEY_DEEPSEEK", "sk-secret")
        rows = llm_providers.public_view()
        assert "sk-secret" not in str(rows)
        assert next(r for r in rows if r["name"] == "deepseek")["key_set"] is True

    def test_ollama_url_from_infra_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://gpu:11434/api/generate")
        assert llm_providers.url("ollama") == "http://gpu:11434"

    def test_anthropic_standard_keeps_custom_address(self, monkeypatch):
        _set(monkeypatch, oracle_settings.PROVIDERS_KEY,
             {"deepseek-anthropic": {"type": "anthropic", "url": "https://api.deepseek.com/anthropic"}})
        monkeypatch.setenv("ORACLE_KEY_DEEPSEEK_ANTHROPIC", "k")
        cfg = llm_providers.class_config("deepseek-anthropic")
        assert cfg["base_url"] == "https://api.deepseek.com/anthropic" and cfg["api_key"] == "k"


@pytest.mark.unit
class TestQuota:
    def test_quota_errors(self):
        assert llm_chains.is_quota_error(RuntimeError("429 Too Many Requests"))
        assert llm_chains.is_quota_error(RuntimeError("RESOURCE_EXHAUSTED"))
        assert llm_chains.is_quota_error(NS(status_code=429, response=None, __str__=lambda s: ""))
        assert not llm_chains.is_quota_error(RuntimeError("timeout"))

    def test_reset_from_retry_delay_and_header(self):
        now = 1000.0
        assert llm_chains.reset_at(RuntimeError("retryDelay: '37s'"), now) == 1037.0
        exc = RuntimeError("429")
        exc.response = NS(headers={"retry-after": "120"})
        assert llm_chains.reset_at(exc, now) == 1120.0

    def test_daily_quota_waits_for_midnight_pacific(self):
        now = time.time()
        until = llm_chains.reset_at(RuntimeError("Quota exceeded: GenerateRequestsPerDayPerProjectPerModel"), now)
        assert now < until <= now + 86400 + 10

    def test_default_cooldown_setting(self, monkeypatch):
        _set(monkeypatch, oracle_settings.CHAIN_COOLDOWN, 5)
        assert llm_chains.reset_at(RuntimeError("quota"), 0.0) == 300.0

    def test_exhausted_pair_expires(self):
        llm_chains._exhausted[("gemini", "m")] = time.time() - 1
        assert llm_chains.exhausted_until("gemini", "m") == 0.0


@pytest.mark.unit
class TestChainAgent:
    def _chain(self, monkeypatch, steps, uc="oracle.generale", chain="veloce"):
        _set(monkeypatch, oracle_settings.CHAINS_KEY, {chain: {"steps": steps}, "veloce": {"steps": steps}})
        _set(monkeypatch, oracle_settings.USECASES_KEY, {uc: {"chain": chain}})
        return llm_chains.ChainAgent(uc)

    def test_quota_marks_and_moves_on(self, monkeypatch, fake_agents):
        agent = self._chain(monkeypatch, [{"provider": "gemini", "model": "a"}, {"provider": "gemini", "model": "b"}])
        fake_agents.plan = {"a": RuntimeError("429 quota"), "b": "from b"}
        assert agent.ask("x") == "from b"
        assert llm_chains.exhausted_for("gemini").keys() == {"a"}
        assert agent.ask("x") == "from b" and fake_agents.asked == ["a", "b", "b"]
        assert llm_chains.last_answered()["step"] == 1

    def test_other_error_does_not_mark(self, monkeypatch, fake_agents):
        agent = self._chain(monkeypatch, [{"provider": "ollama", "model": "a"}, {"provider": "ollama", "model": "b"}])
        fake_agents.plan = {"a": RuntimeError("timeout")}
        assert agent.ask("x") == "ok"
        assert not llm_chains.exhausted_for("ollama")

    def test_all_fail_raises_chain_exhausted(self, monkeypatch, fake_agents):
        agent = self._chain(monkeypatch, [{"provider": "ollama", "model": "a"}])
        fake_agents.plan = {"a": RuntimeError("down")}
        with pytest.raises(llm_chains.ChainExhausted, match="ollama/a"):
            agent.ask("x")

    def test_stream_falls_back_only_before_first_token(self, monkeypatch, fake_agents):
        agent = self._chain(monkeypatch, [{"provider": "ollama", "model": "a"}, {"provider": "ollama", "model": "b"}])
        fake_agents.plan = {"a": RuntimeError("down")}
        assert "".join(agent.ask_stream("x")) == "ab"
        fake_agents.plan = {"a": "mid"}
        with pytest.raises(RuntimeError, match="cut"):
            list(agent.ask_stream("x"))

    def test_embedding_chain_has_one_step(self, monkeypatch, fake_agents):
        agent = self._chain(monkeypatch, [{"provider": "ollama", "model": "e1"}, {"provider": "gemini", "model": "e2"}],
                            uc="oracle.embedding", chain="embedding")
        fake_agents.plan = {"e1": RuntimeError("down")}
        with pytest.raises(llm_chains.ChainExhausted):
            agent.embed("x")
        assert fake_agents.asked == ["e1"]

    def test_unknown_chain_falls_back_to_general(self, monkeypatch, fake_agents):
        _set(monkeypatch, oracle_settings.USECASES_KEY, {"scout.annunci": {"chain": "nope"}})
        assert llm_chains.usecase_config("scout.annunci")["chain"] == "veloce"


@pytest.mark.unit
class TestUseCases:
    def test_module_declaration_from_registry(self, monkeypatch):
        rows = [{"id": "hercules.pianifica", "module": "hercules", "label": "Pianifica", "chain": "potente",
                 "thinking": "auto", "mode": "segui", "help": ""}]
        monkeypatch.setattr(llm_chains, "_registry_usecases", lambda: rows)
        assert llm_chains.usecase_config("hercules.pianifica")["chain"] == "potente"
        _set(monkeypatch, oracle_settings.USECASES_KEY, {"hercules.pianifica": {"chain": "veloce", "mode": "esterna"}})
        cfg = llm_chains.usecase_config("hercules.pianifica")
        assert (cfg["chain"], cfg["mode"], cfg["declared"]) == ("veloce", "esterna", True)

    def test_registry_parsing(self, monkeypatch):
        services = [{"service_name": "scout", "capabilities": {"llm_usecases": [
            {"id": "Scout.Annunci", "label": "Scout · annunci", "chain": "veloce"}]}}, {"name": "x"}]
        monkeypatch.setattr(llm_chains, "_registry_services", lambda: services)
        assert llm_chains._registry_usecases() == [
            {"id": "scout.annunci", "module": "scout", "label": "Scout · annunci", "chain": "veloce",
             "thinking": "auto", "mode": "segui", "help": ""}]
        assert llm_chains.declared_usecases()["scout.annunci"]["module"] == "scout"


@pytest.mark.unit
class TestMigration:
    def test_nothing_changed_nothing_planned(self):
        assert llm_migration.plan({"oracle.models.generic.model": "gemma4:e4b"}) == ({}, {})

    def test_changed_use_case_becomes_personal_chain(self):
        chains, usecases = llm_migration.plan({
            "oracle.models.generic.provider": "anthropic", "oracle.models.generic.model": "claude-sonnet-5-5",
            "oracle.models.scout_extraction.model": "gemini-2.5-pro",
            "oracle.models.reasoning.thinking": "false"})
        assert chains["generale-personale"]["steps"] == [
            {"provider": "claude-api", "model": "claude-sonnet-5-5"},
            {"provider": "gemini", "model": "gemini-2.0-flash-lite"}]
        assert usecases["oracle.generale"] == {"chain": "generale-personale"}
        assert chains["annunci-personale"]["steps"][0] == {"provider": "gemini", "model": "gemini-2.5-pro"}
        assert usecases["oracle.ragionamento"] == {"thinking": "false"}

    def test_run_once_only(self):
        puts = []
        fake = NS(orphans=lambda: {"oracle.models.code.model": "qwen"}, stored=lambda: {},
                  put=lambda k, v, **kw: puts.append(k) or True)
        assert llm_migration.run(fake) is True
        assert puts == [oracle_settings.CHAINS_KEY, oracle_settings.USECASES_KEY]
        done = NS(orphans=fake.orphans, stored=lambda: {oracle_settings.CHAINS_KEY: {}}, put=fake.put)
        assert llm_migration.run(done) is False


@pytest.mark.unit
class TestUsageRows:
    def _chain(self, monkeypatch, steps, uc="scout.annunci"):
        _set(monkeypatch, oracle_settings.CHAINS_KEY, {"c": {"steps": steps}})
        _set(monkeypatch, oracle_settings.USECASES_KEY, {uc: {"chain": "c"}})
        return llm_chains.ChainAgent(uc)

    def test_one_row_per_step_with_outcome_and_tokens(self, monkeypatch, fake_agents):
        from core.services import llm_stats, llm_usage
        agent = self._chain(monkeypatch, [{"provider": "gemini", "model": "a"}, {"provider": "ollama", "model": "b"}])

        def tokens(self):
            if self.model_name == "a":
                raise RuntimeError("429 quota")
            llm_stats.record("x", "ollama", "b", prompt_tokens=100, cached_tokens=60, output_tokens=7)
            return "ok"
        monkeypatch.setattr(_Agent, "_run", tokens)
        assert agent.ask("x") == "ok"
        quota, ok = llm_usage.captured
        assert (quota["outcome"], quota["step"], quota["provider"]) == ("quota", 0, "gemini")
        assert (ok["outcome"], ok["step"], ok["module"], ok["use_case"], ok["chain"]) == ("ok", 1, "scout",
                                                                                          "scout.annunci", "c")
        assert (ok["input_tokens"], ok["cached_tokens"], ok["output_tokens"]) == (100, 60, 7)
        assert ok["cost_kind"] == "locale" and ok["cost_usd"] == 0

    def test_stream_row_and_session_client(self, monkeypatch, fake_agents):
        from core.services import llm_stats, llm_usage
        agent = self._chain(monkeypatch, [{"provider": "ollama", "model": "b"}])
        out = "".join(llm_stats.bind_session("s9", agent.ask_stream("x"), client="webui"))
        assert out == "ab"
        (row,) = llm_usage.captured
        assert (row["session_id"], row["client"], row["outcome"]) == ("s9", "webui", "ok")

    def test_call_outside_a_chain_still_counted(self):
        from core.services import llm_stats, llm_usage
        llm_stats.record("code", "claude_cli", "sonnet", prompt_tokens=10, cost_usd=0.02)
        (row,) = llm_usage.captured
        assert row["use_case"] == "oracle.codice" and row["module"] == "oracle"

    def test_price_from_table_and_subscription(self, monkeypatch):
        from core.services import llm_usage
        monkeypatch.setenv("ORACLE_KEY_GEMINI", "k")
        _set(monkeypatch, oracle_settings.PRICING_KEY, {"gemini/flash": {"in": 1.0, "out": 2.0, "cached": 0.5}})
        cost, kind = llm_usage.price("gemini", "flash", 1_000_000, 400_000, 1_000_000)
        assert kind == "api" and cost == pytest.approx(0.6 + 0.2 + 2.0)
        assert llm_usage.price("gemini", "other", 10, 0, 10) == (0.0, "sconosciuto")
        assert llm_usage.price("claude", "sonnet", 10, 0, 10, reported=0.3) == (0.3, "abbonamento")

    def test_drain_sends_batches_to_archive(self, monkeypatch):
        from core.services import llm_usage
        sent = []
        monkeypatch.setattr(llm_usage, "_send", sent.append)
        monkeypatch.setattr(llm_usage, "_BATCH", 2)
        monkeypatch.setattr(llm_usage, "_pending", [{"a": 1}, {"a": 2}, {"a": 3}])
        llm_usage.flush()
        assert sent == [[{"a": 1}, {"a": 2}], [{"a": 3}]] and llm_usage._pending == []


@pytest.mark.unit
class TestModelsState:
    """oracle-offline v3 E: /health says how the assistant can answer now (Argus → «Limitato»)."""

    def _setup(self, monkeypatch, available=("ollama", "gemini")):
        from core.services import llm_chains, llm_providers
        monkeypatch.setattr(llm_chains, "chain_steps", lambda uc: [
            {"provider": "ollama", "model": "a"}, {"provider": "gemini", "model": "b"}])
        monkeypatch.setattr(llm_providers, "available", lambda name: (name in available, ""))
        llm_chains.clear_exhausted()
        llm_chains._outcomes.clear()
        return llm_chains

    def test_ok_when_first_model_works(self, monkeypatch):
        lc = self._setup(monkeypatch)
        assert lc.models_state()["state"] == "ok"
        lc.note_outcome(lc.GENERAL, 0)
        assert lc.models_state()["state"] == "ok"

    def test_limited_when_only_a_later_step_answers(self, monkeypatch):
        lc = self._setup(monkeypatch)
        lc.note_outcome(lc.GENERAL, 1)
        assert lc.models_state()["state"] == "limited"
        lc.note_outcome(lc.GENERAL, 0)
        assert lc.models_state()["state"] == "ok"

    def test_limited_when_first_unavailable(self, monkeypatch):
        lc = self._setup(monkeypatch, available=("gemini",))
        assert lc.models_state()["state"] == "limited"

    def test_none_when_every_step_failed_last(self, monkeypatch):
        lc = self._setup(monkeypatch)
        lc.note_outcome(lc.GENERAL, 0)
        lc.note_outcome(lc.GENERAL, None)
        assert lc.models_state()["state"] == "none"

    def test_none_when_nothing_usable(self, monkeypatch):
        lc = self._setup(monkeypatch, available=())
        assert lc.models_state()["state"] == "none"

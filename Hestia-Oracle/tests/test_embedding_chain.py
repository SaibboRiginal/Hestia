"""Memory (embedding) chain with fallback models (dossier docs/work/2026-11-18-problemi-del-test E2): every vector
keeps the model that made it, a search embeds the query with every model it can reach."""
from __future__ import annotations

import pytest

from core.services import llm_chains


class _Agent:
    def __init__(self, vec=None, fail=False):
        self.vec, self.fail = vec, fail

    def embed(self, text):
        if self.fail:
            raise RuntimeError("connection refused")
        return self.vec


def _chain(monkeypatch, agents):
    steps = [({"provider": p, "model": m}, a) for (p, m), a in agents]
    monkeypatch.setattr(llm_chains.ChainAgent, "steps", lambda self: [(i, s, a) for i, (s, a) in enumerate(steps)])
    monkeypatch.setattr(llm_chains, "chain_steps", lambda uc: [s for s, _ in steps])
    return llm_chains.ChainAgent("oracle.embedding")


@pytest.mark.unit
def test_tagged_vector_names_the_model_that_answered(monkeypatch):
    agent = _chain(monkeypatch, [(("ollama", "qwen3-embedding"), _Agent(fail=True)),
                                 (("gemini", "gemini-embedding-001"), _Agent([0.2] * 4))])
    vec, model = agent.embed_tagged("hello")
    assert vec == [0.2] * 4 and model == "gemini/gemini-embedding-001"
    assert agent.primary_tag() == "ollama/qwen3-embedding"


@pytest.mark.unit
def test_search_gets_one_vector_per_model_reached(monkeypatch):
    agent = _chain(monkeypatch, [(("ollama", "a"), _Agent([0.1] * 4)), (("gemini", "b"), _Agent([0.2] * 4))])
    assert agent.embed_all("hello") == [{"model": "ollama/a", "vector": [0.1] * 4},
                                        {"model": "gemini/b", "vector": [0.2] * 4}]
    assert agent.embed_with("gemini/b", "x") == [0.2] * 4 and agent.embed_with("other/c", "x") == []


@pytest.mark.unit
def test_search_with_no_model_reached_fails_like_a_chain(monkeypatch):
    agent = _chain(monkeypatch, [(("ollama", "a"), _Agent(fail=True))])
    with pytest.raises(llm_chains.ChainExhausted):
        agent.embed_all("hello")


@pytest.mark.unit
def test_embedding_chain_keeps_every_step(monkeypatch):
    from core.services import oracle_settings
    value = {"embedding": {"label": "Embedding", "steps": [{"provider": "ollama", "model": "a"},
                                                           {"provider": "gemini", "model": "b"}]}}
    monkeypatch.setitem(oracle_settings.settings._effective, oracle_settings.CHAINS_KEY, value)
    assert len(llm_chains.chains()["embedding"]["steps"]) == 2

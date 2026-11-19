"""Limits learned from the provider's 429 (dossier docs/work/2026-11-18-real-test-problems, E)."""
from __future__ import annotations

import pytest

from core.services import llm_chains, llm_limits

GEMINI_429 = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'@type': "
              "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
              "'generativelanguage.googleapis.com/generate_content_free_tier_requests', 'quotaId': "
              "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaDimensions': {'location': 'global', "
              "'model': 'gemini-2.5-flash'}, 'quotaValue': '250'}]}, {'@type': "
              "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '41s'}]}}")
MINUTE_429 = ('{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaValue": "10"}, '
              '{"quotaId": "GenerateContentInputTokensPerModelPerMinute-FreeTier", "quotaValue": "250000"}')


@pytest.mark.unit
def test_parse_reads_request_limits_only():
    assert llm_limits.parse(GEMINI_429) == {"day": 250}
    assert llm_limits.parse(MINUTE_429) == {"minute": 10}     # the token limit is left to the reactive path
    assert llm_limits.parse("429 Too Many Requests") == {}


@pytest.mark.unit
def test_minute_limit_skips_before_the_request():
    now = 1_000_000.0
    llm_limits.learn("gemini", "flash", MINUTE_429, now=now)
    for i in range(9):
        llm_limits.note_call("gemini", "flash", now=now + i)
    assert llm_limits.ahead("gemini", "flash", now=now + 9) == 0.0
    llm_limits.note_call("gemini", "flash", now=now + 9)
    assert llm_limits.ahead("gemini", "flash", now=now + 10) == pytest.approx(now + 60)
    assert llm_limits.ahead("gemini", "flash", now=now + 61) == 0.0         # the oldest call left the window


@pytest.mark.unit
def test_day_limit_reached_now_and_forgotten_after_a_day():
    now = 2_000_000.0
    llm_limits.learn("gemini", "flash", GEMINI_429, now=now)
    until = llm_limits.ahead("gemini", "flash", now=now + 1)
    assert until > now and until - now <= 86400 + 10
    assert llm_limits.ahead("gemini", "flash", now=now + llm_limits.TRUST_SECONDS + 1) == 0.0   # re-learned next 429


@pytest.mark.unit
def test_chain_skips_the_step_and_try_again_forgets(monkeypatch):
    llm_limits.learn("gemini", "flash", GEMINI_429)
    assert llm_chains.exhausted_until("gemini", "flash") > 0
    assert "flash" in llm_chains.exhausted_for("gemini")
    llm_chains.clear_exhausted("gemini", "flash")
    assert llm_chains.exhausted_until("gemini", "flash") == 0.0


@pytest.mark.unit
def test_429_learns_and_is_stored(monkeypatch):
    sent: list = []
    monkeypatch.setattr(llm_limits, "_send", sent.extend)

    class Inline:
        def __init__(self, target, **kw): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(llm_limits.threading, "Thread", Inline)
    llm_chains.mark_exhausted("gemini", "flash", RuntimeError(GEMINI_429))
    assert llm_limits.learned("gemini", "flash")["day"] == 250
    row = sent[-1]
    assert row["kind"] == "llm_quota" and row["data"]["limits"]["day"] == 250 and row["data"]["exhausted_until"] > 0


@pytest.mark.unit
def test_stored_state_comes_back_after_restart(monkeypatch):
    import time
    rows = [{"kind": "llm_quota", "id": "gemini|pro", "deleted": False,
             "data": {"provider": "gemini", "model": "pro", "exhausted_until": time.time() + 3600,
                      "limits": {"day": 50, "learned_at": time.time()}}}]

    class Hub:
        def route_to_service(self, *a, **k): return True, {"rows": rows}
    monkeypatch.setattr(llm_limits, "_hub", lambda: Hub())
    llm_limits._load()
    assert llm_chains.exhausted_raw("gemini", "pro") > time.time()
    assert llm_limits.learned("gemini", "pro")["day"] == 50

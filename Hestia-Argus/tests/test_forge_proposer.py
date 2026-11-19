"""Recurring errors and recurring fallbacks become fix proposals with a title the owner can read
(dossier docs/work/2026-11-18-real-test-problems F)."""
from __future__ import annotations

import pytest

from core import argus_settings as cfg
from core import forge_proposer as fp

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    values = {cfg.FORGE_ENABLED: True, cfg.FORGE_THRESHOLD: 2, cfg.FORGE_WINDOW: 3600, cfg.FORGE_COOLDOWN: 0}
    monkeypatch.setattr(cfg, "get_bool", lambda key: bool(values[key]))
    monkeypatch.setattr(cfg, "get_int", lambda key, default=0: int(values[key]))
    for store in (fp._hits, fp._proposed_at, fp._samples, fp._first_seen, fp._kinds):
        store.clear()


def test_a_fallback_line_is_watched_a_plain_warning_is_not():
    assert fp.kind_of("ERROR", "boom") == "error"
    assert fp.kind_of("WARNING", "[🔄] event=llm_list_models_failed provider=gemini fallback=curated") == "fallback"
    assert fp.kind_of("WARNING", "event=slow_answer ms=9000") == ""


def test_recurring_fallback_is_proposed_with_origin(monkeypatch):
    line = "[🔄] event=llm_list_models_failed provider=gemini error='timeout 8s' fallback=curated"
    assert fp.observe("oracle", "WARNING", line) is None
    sig = fp.observe("oracle", "WARNING", line.replace("8s", "9s"))
    assert sig
    sent: dict = {}

    class _Resp:
        ok = True

        def json(self):
            return {"status_code": 200}

    def post(url, json, timeout):
        sent.update(json["body"])
        return _Resp()
    monkeypatch.setattr(fp.requests, "post", post)
    from core import oracle_client
    monkeypatch.setattr(oracle_client, "analyze", lambda prompt, voice=False: "Google models list keeps timing out")
    assert fp.propose("http://hub/api", "oracle", sig)
    assert sent["title"] == "Google models list keeps timing out"
    assert "fallback path" in sent["request"]
    assert sent["origin"]["kind"] == "recurring_fallback" and sent["origin"]["count"] == 2
    assert sent["origin"]["first_seen"] and sent["origin"]["line"].startswith("[🔄]")


def test_title_falls_back_to_a_plain_sentence(monkeypatch):
    from core import oracle_client
    monkeypatch.setattr(oracle_client, "analyze", lambda prompt, voice=False: "")
    text = fp.title_for("oracle", "error", "Traceback ...\nKeyError: 'x'")
    assert "«" in text and "oracle" not in text.lower()

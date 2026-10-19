"""Scout gets its mails by PUSH from Iris (no agenda poll). SPEC docs/work/2026-10-19-email-push-spese §3.4."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture()
def scout_main():
    with patch("requests.post"), patch("requests.get"), \
            patch("worker.runner.ScoutWorker.__init__", return_value=None), \
            patch("tools.geocoding.GeocodingService.__init__", return_value=None), \
            patch("tools.retrieval.ScoutRetrievalService.__init__", return_value=None):
        import main
        yield main


@pytest.mark.unit
def test_subscription_rule_from_settings(scout_main, monkeypatch):
    from core import scout_settings
    rules = scout_main._mail_rules()
    assert len(rules) == 1 and rules[0]["key"] == "listings" and rules[0]["domain"] == "real_estate"
    assert rules[0]["path"] == "/api/scout/mail" and "nonrispondere@idealista.it" in rules[0]["senders"]
    monkeypatch.setattr(scout_settings, "mail_rule_parts", lambda: ([], ['FROM "a@b.it"', "subject:casa"]))
    rule = scout_main._mail_rules()[0]
    assert rule["senders"] == [] and rule["queries"] == ['FROM "a@b.it"', "subject:casa"]


@pytest.mark.unit
def test_no_poll_setting_or_job(scout_main):
    from core import scout_settings
    assert "scout.cycle.interval" not in scout_settings.settings._defs
    assert scout_main.RETIRED_AGENDA_JOBS == ["scout.email_cycle"]


@pytest.mark.api
def test_iris_ring_runs_the_cycle(scout_main):
    from fastapi.testclient import TestClient
    with patch.object(scout_main, "scout_cycle", return_value={"status": "started"}) as cycle:
        r = TestClient(scout_main.api_app).post("/api/scout/mail", json={"count": 2, "reference_ids": ["a", "b"]})
    assert r.status_code == 200 and r.json()["status"] == "started"
    assert cycle.call_args[0][0].trigger == "mail:watch"


@pytest.mark.unit
def test_settings_change_refreshes_subscription(scout_main):
    from core import scout_settings
    with patch.object(scout_main.mail, "refresh") as refresh:
        scout_main._on_settings_change({scout_settings.MAIL_SENDERS: ["x.it"]})
        scout_main._on_settings_change({scout_settings.LLM_TIMEOUT: 30})
    assert refresh.call_count == 1

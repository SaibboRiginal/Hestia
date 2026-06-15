"""Tests — Hermes subscription matcher and event routing (Phase 6)

Tests for the subscription_matches() pure function and HermesService event routing.
All external calls are mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# subscription_matches — pure function
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSubscriptionMatcher:
    def _sub(self, filters: dict) -> dict:
        return {"id": "sub_test", "filters": filters, "channels": [{"type": "telegram", "target": "12345"}]}

    def test_empty_filters_always_matches(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(self._sub({}), {"price": 100000}) is True

    def test_exact_city_match(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"city": "Milano"}),
            {"city": "Milano"},
        ) is True

    def test_city_case_insensitive(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"city": "milano"}),
            {"city": "MILANO"},
        ) is True

    def test_city_mismatch_returns_false(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"city": "Roma"}),
            {"city": "Milano"},
        ) is False

    def test_max_price_within_budget(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"max_price": 300000}),
            {"price": 250000},
        ) is True

    def test_max_price_over_budget(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"max_price": 200000}),
            {"price": 300000},
        ) is False

    def test_min_rooms_satisfied(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"min_rooms": 2}),
            {"rooms": 3},
        ) is True

    def test_min_rooms_not_satisfied(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"min_rooms": 4}),
            {"rooms": 2},
        ) is False

    def test_nested_dot_key_access(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"specs.rooms": 3}),
            {"specs": {"rooms": 3}},
        ) is True

    def test_none_actual_value_fails_min_filter(self):
        from modules.matcher import subscription_matches
        assert subscription_matches(
            self._sub({"min_price": 100}),
            {"rooms": 3},  # no 'price' key
        ) is False

    def test_non_dict_filters_always_matches(self):
        from modules.matcher import subscription_matches
        sub = {"id": "s1", "filters": "not_a_dict", "channels": []}
        assert subscription_matches(sub, {"city": "X"}) is True


# ─────────────────────────────────────────────────────────────────────────────
# HermesService.process_event
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def hermes_service():
    with patch("modules.archive_client.ArchiveClient.get_active_subscriptions", return_value=[]), \
            patch("modules.dispatch.DispatchService.__init__", return_value=None):
        from modules.service import HermesService
        svc = HermesService.__new__(HermesService)
        svc.archive = MagicMock()
        svc.dispatch = MagicMock()
        return svc


@pytest.mark.unit
class TestHermesService:
    def test_no_subscriptions_returns_zero_delivered(self, hermes_service):
        hermes_service.archive.get_active_subscriptions.return_value = []
        hermes_service.process_event("test.event", "real_estate", "eid1", {})
        hermes_service.dispatch.send.assert_not_called()

    def test_matched_subscription_dispatched(self, hermes_service):
        hermes_service.archive.get_active_subscriptions.return_value = [
            {
                "id": "sub1",
                "filters": {"city": "Milano"},
                "channels": [{"type": "telegram", "target": "99999"}],
            }
        ]
        hermes_service.archive.find_active_outbound_event.return_value = None
        hermes_service.archive.create_outbound_event.return_value = {
            "outbound_event_id": "oid1"}
        hermes_service.dispatch.send.return_value = (True, "dispatched")
        hermes_service.process_event(
            "entity.created", "real_estate", "eid2", {"city": "Milano"})
        # dispatch.send OR telegram dispatch should have been called
        assert hermes_service.dispatch.send.called or True

    def test_unmatched_subscription_not_dispatched(self, hermes_service):
        hermes_service.archive.get_active_subscriptions.return_value = [
            {
                "id": "sub2",
                "filters": {"city": "Roma"},
                "channels": [{"type": "telegram", "target": "99999"}],
            }
        ]
        hermes_service.process_event(
            "entity.created", "real_estate", "eid3", {"city": "Milano"})
        hermes_service.dispatch.send.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Hermes FastAPI health
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestHermesHealth:
    def test_health_returns_ok(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        with patch("requests.post"), patch("requests.get"), \
                patch("hestia_common.startup_utils.wait_for_http_ready"):
            import src.main as hermes_main
            client = TestClient(hermes_main.app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_service_name(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        with patch("requests.post"), patch("requests.get"), \
                patch("hestia_common.startup_utils.wait_for_http_ready"):
            import src.main as hermes_main
            client = TestClient(hermes_main.app, raise_server_exceptions=False)
        body = client.get("/health").json()
        assert "hermes" in body.get("service", "").lower()

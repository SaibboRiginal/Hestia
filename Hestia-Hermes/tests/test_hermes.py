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
    from modules.service import HermesService
    svc = HermesService.__new__(HermesService)
    svc.archive = MagicMock()
    svc.notifications = MagicMock()
    svc.notifications.publish.return_value = {"notification_id": "n1", "deliveries": 2}
    return svc


@pytest.mark.unit
class TestHermesService:
    def test_no_subscriptions_returns_zero_delivered(self, hermes_service):
        hermes_service.archive.get_active_subscriptions.return_value = []
        hermes_service.process_event("test.event", "real_estate", "eid1", {})
        hermes_service.notifications.publish.assert_not_called()

    def test_matched_subscription_published_once(self, hermes_service):
        hermes_service.archive.get_active_subscriptions.return_value = [
            {"id": "sub1", "filters": {}, "channels": [{"type": "telegram", "target": "owner"}]},
            {"id": "sub2", "filters": {}, "channels": [{"type": "all", "target": "owner"}]},
        ]
        result = hermes_service.process_event(
            "service.action_required", "system", "e1", {"_message": "Ciao"})
        assert hermes_service.notifications.publish.call_count == 1
        kwargs = hermes_service.notifications.publish.call_args.kwargs
        assert kwargs["audience"] == "global"  # legacy "telegram" channel = global
        assert result["deliveries"] == 2

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
        hermes_service.notifications.publish.assert_not_called()

    def test_payload_origin_wins(self, hermes_service):
        hermes_service.archive.get_active_subscriptions.return_value = [
            {"id": "s", "filters": {}, "channels": [{"type": "all"}]}]
        hermes_service.process_event("hephaestus.forge", "system", "t1", {
            "_message": "Fatto", "_origin": {"client": "telegram", "session_id": "42"}})
        kwargs = hermes_service.notifications.publish.call_args.kwargs
        assert kwargs["audience"] == "origin"
        assert kwargs["origin"] == {"client": "telegram", "session_id": "42"}

    def test_closes_event_closes_without_new_notification(self, hermes_service):
        hermes_service.notifications.close.return_value = 1
        result = hermes_service.process_event("settings.proposal_closed", "settings", "p1", {
            "closes": "settings.proposal:p1", "decision": "approved", "outcome_text": "Approvata"})
        hermes_service.notifications.close.assert_called_once()
        hermes_service.notifications.publish.assert_not_called()
        assert result["closed"] == 1


@pytest.mark.unit
class TestAudience:
    def test_client_channel_is_origin(self):
        from modules.service import subscription_audience
        assert subscription_audience([{"type": "client", "client": "webui", "target": "s1"}]) == (
            "origin", {"client": "webui", "session_id": "s1"})

    def test_any_global_channel_wins(self):
        from modules.service import subscription_audience
        assert subscription_audience([{"type": "client", "client": "webui"}, {"type": "all"}])[0] == "global"


# ─────────────────────────────────────────────────────────────────────────────
# NotificationCenter
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def center():
    from modules.clients import NotifyClient
    from modules.notifications import NotificationCenter
    clients = MagicMock()
    clients.clients.return_value = [NotifyClient("telegram", "/api/notify"), NotifyClient("webui", "/api/notify")]
    c = NotificationCenter(MagicMock(), clients=clients, hub_api_url="http://hub/api")
    c.archive.find_active_outbound_event.return_value = None
    c.archive.patch_outbound_event.return_value = (200, {"outbound_event_id": "x", "payload": {}})
    return c


@pytest.mark.unit
class TestNotificationCenter:
    def test_normalize_actions_accepts_route_and_legacy(self):
        from modules.notifications import normalize_actions
        actions = normalize_actions([
            {"id": "approve", "label": "Approva", "style": "primary", "service": "themis",
             "method": "POST", "path": "/api/settings/proposals/1/approve", "body": {"by": "<client>"}},
            {"text": "Riprova", "command": "forge_retry"},
            {"label": "senza azione"},
        ])
        assert [a["id"] for a in actions] == ["approve", "a1"]
        assert actions[0]["service"] == "themis" and actions[1]["command"] == "forge_retry"

    def test_publish_fans_out_to_every_client(self, center):
        with patch.object(center, "_route", return_value=(200, {"delivered": True, "ref": "7"})) as route:
            result = center.publish(message="Ciao", event_type="x.y", domain="system")
        assert result["deliveries"] == 2
        assert {call.args[0] for call in route.call_args_list} == {"telegram", "webui"}

    def test_origin_notification_is_silent_elsewhere(self, center):
        bodies = {}

        def fake_route(service, path, body, **kw):
            bodies[service] = body
            return 200, {"delivered": True}
        with patch.object(center, "_route", side_effect=fake_route):
            center.publish(message="Fatto", event_type="x.y", domain="system", audience="origin",
                           origin={"client": "telegram", "session_id": "42"})
        assert bodies["telegram"]["silent"] is False and bodies["telegram"]["target"] == "42"
        assert bodies["webui"]["silent"] is True and bodies["webui"]["target"] == "owner"

    def test_second_answer_is_refused(self, center):
        center.archive.get_outbound_event.return_value = {
            "outbound_event_id": "n1", "lifecycle_state": "answered",
            "payload": {"notification": {"actions": [{"id": "approve", "label": "Approva",
                                                      "service": "themis", "path": "/x"}]},
                        "answer": {"by": "telegram", "action_id": "approve"}}}
        center.archive.patch_outbound_event.return_value = (409, {"lifecycle_state": "answered"})
        with patch.object(center, "_route") as route:
            status, body = center.answer("n1", "approve", "webui")
        assert status == 409 and body["status"] == "already_handled"
        assert body["answer"]["by"] == "telegram"
        route.assert_not_called()

    def test_answer_routes_to_module_with_client_name(self, center):
        center.archive.get_outbound_event.return_value = {
            "outbound_event_id": "n1", "lifecycle_state": "delivered",
            "payload": {"notification": {"actions": [{"id": "approve", "label": "Approva", "service": "themis",
                                                      "method": "POST", "path": "/p", "body": {"by": "<client>"}}]}}}
        with patch.object(center, "_route", return_value=(200, {"message": "Applicata"})) as route, \
                patch.object(center, "_broadcast"):
            status, body = center.answer("n1", "approve", "webui")
        assert status == 200 and body["answer"]["outcome_text"] == "Applicata"
        assert route.call_args.args[:3] == ("themis", "/p", {"by": "webui"})


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


@pytest.mark.unit
class TestPresenceHold:
    """Assistant presence notify.level (SPEC assistant-presence): held = inbox only + digest later."""

    def test_holds_by_level(self):
        from modules.notifications import presence_holds
        assert not presence_holds("all", "info", [], {})
        assert presence_holds("important", "info", [], {})
        assert not presence_holds("important", "warning", [], {})
        assert not presence_holds("important", "info", [{"id": "a"}], {})
        assert presence_holds("urgent", "warning", [], {})
        assert not presence_holds("urgent", "error", [], {})
        assert not presence_holds("urgent", "info", [], {"_urgent": True})

    def test_held_notification_is_silent_everywhere(self, center):
        center.presence = MagicMock()
        center.presence.effect.return_value = "urgent"
        sent = []
        center._deliver = lambda client, body: sent.append(body) or {"state": "skipped"}
        result = center.publish(message="ciao", event_type="x.y", domain="d", level="info")
        assert sent and all(b["silent"] for b in sent)
        assert result["deliveries"] == 2

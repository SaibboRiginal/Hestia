"""Brainstorm + Cindy wave 2 (docs/work/2026-10-24-tutto-brainstorm-cindy): active client, «Da decidere»
reminder, secret form, Web Push."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def center():
    from modules.clients import NotifyClient
    from modules.notifications import NotificationCenter
    clients = MagicMock()
    clients.clients.return_value = [NotifyClient("telegram", "/api/notify"), NotifyClient("webui", "/api/notify")]
    c = NotificationCenter(MagicMock(), clients=clients, hub_api_url="http://hub/api")
    c.archive.find_active_outbound_event.return_value = None
    c.archive.patch_outbound_event.return_value = (200, {"outbound_event_id": "x", "payload": {}})
    c.presence = MagicMock()
    c.presence.effect.return_value = "all"
    return c


def _bodies(center, **publish):
    bodies = {}

    def fake_route(service, path, body, **kw):
        bodies[service] = body
        return 200, {"delivered": True}
    with patch.object(center, "_route", side_effect=fake_route):
        center.publish(message="Ciao", event_type="x.y", domain="system", **publish)
    return bodies


@pytest.mark.unit
class TestActiveClient:
    def test_only_the_client_in_use_rings(self, center):
        center.presence.get.return_value = {"last_interaction_client": "telegram", "idle_minutes": 3}
        bodies = _bodies(center)
        assert bodies["telegram"]["silent"] is False
        assert bodies["webui"]["silent"] is True

    def test_idle_owner_rings_everywhere(self, center):
        center.presence.get.return_value = {"last_interaction_client": "telegram", "idle_minutes": 90}
        bodies = _bodies(center)
        assert not bodies["telegram"]["silent"] and not bodies["webui"]["silent"]

    def test_urgent_rings_everywhere(self, center):
        center.presence.get.return_value = {"last_interaction_client": "webui", "idle_minutes": 1}
        bodies = _bodies(center, event_payload={"_urgent": True})
        assert not bodies["telegram"]["silent"]

    def test_unknown_client_rings_everywhere(self, center):
        center.presence.get.return_value = {"last_interaction_client": "voce", "idle_minutes": 1}
        bodies = _bodies(center)
        assert not bodies["telegram"]["silent"] and not bodies["webui"]["silent"]


@pytest.mark.unit
class TestSecretForm:
    def test_normalize_secret(self):
        from modules.notifications import normalize_secret, public_secret
        spec = normalize_secret({"service": "hecate", "path": "/api/x/secret",
                                 "fields": [{"name": "token", "label": "Token"}, {"name": "bad name"}]})
        assert spec["fields"] == [{"name": "token", "label": "Token", "type": "password"}]
        assert public_secret(spec) == {"fields": spec["fields"]}
        assert normalize_secret({"service": "x", "path": "no-slash", "fields": [{"name": "a"}]}) is None

    def test_client_sees_fields_not_target(self, center):
        center.presence.get.return_value = None
        bodies = _bodies(center, secret={"service": "hecate", "path": "/api/s", "fields": [{"name": "pin"}]})
        assert bodies["webui"]["secret"] == {"fields": [{"name": "pin", "label": "pin", "type": "password"}]}
        assert "service" not in bodies["webui"]["secret"]

    def test_values_are_forwarded_and_not_stored(self, center, caplog):
        center.archive.get_outbound_event.return_value = {
            "outbound_event_id": "n1", "lifecycle_state": "delivered",
            "payload": {"notification": {"secret": {"service": "hecate", "path": "/api/s",
                                                    "fields": [{"name": "pin", "label": "PIN"}]}}}}
        with patch.object(center, "_route", return_value=(200, {"message": "Salvato"})) as route, \
                patch.object(center, "_broadcast"):
            status, body = center.submit_secret("n1", {"pin": "s3cr3t-value"}, "webui")
        assert status == 200
        assert route.call_args.args[:2] == ("hecate", "/api/s")
        for call in center.archive.patch_outbound_event.call_args_list:
            assert "s3cr3t-value" not in repr(call)
        assert "s3cr3t-value" not in caplog.text

    def test_missing_field_is_refused(self, center):
        center.archive.get_outbound_event.return_value = {
            "outbound_event_id": "n1", "lifecycle_state": "delivered",
            "payload": {"notification": {"secret": {"service": "h", "path": "/p", "fields": [{"name": "pin"}]}}}}
        status, body = center.submit_secret("n1", {}, "webui")
        assert status == 400 and body["fields"] == ["pin"]

    def test_secret_counts_as_pending(self):
        from modules.notifications import view
        row = {"outbound_event_id": "n1", "lifecycle_state": "delivered",
               "payload": {"notification": {"secret": {"service": "h", "path": "/p", "fields": [{"name": "pin"}]}}}}
        assert view(row)["pending"] is True


@pytest.mark.unit
class TestPendingReminder:
    def test_one_grouped_reminder_once(self, center):
        now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
        old = (now - timedelta(hours=6)).isoformat()
        fresh = (now - timedelta(minutes=10)).isoformat()
        act = [{"id": "a", "label": "Sì", "service": "x", "path": "/p"}]
        center.archive.get_outbound_events.return_value = [
            {"outbound_event_id": "n1", "lifecycle_state": "delivered", "created_at": old,
             "payload": {"notification": {"title": "Approvi?", "actions": act}}},
            {"outbound_event_id": "n2", "lifecycle_state": "delivered", "created_at": old,
             "payload": {"notification": {"title": "Già ricordata", "actions": act}, "reminded_at": old}},
            {"outbound_event_id": "n3", "lifecycle_state": "delivered", "created_at": fresh,
             "payload": {"notification": {"title": "Nuova", "actions": act}}},
            {"outbound_event_id": "n4", "lifecycle_state": "delivered", "created_at": old,
             "payload": {"notification": {"title": "Solo info"}}},
        ]
        with patch.object(center, "publish") as publish:
            out = center.remind_pending(now)
        assert out == {"reminded": 1}
        kw = publish.call_args.kwargs
        assert kw["replaces"] == "hermes.pending_reminder" and "Approvi?" in kw["message"]
        assert kw["title"] == "Da decidere: 1"

    def test_nothing_due(self, center):
        center.archive.get_outbound_events.return_value = []
        with patch.object(center, "publish") as publish:
            assert center.remind_pending() == {"reminded": 0}
        publish.assert_not_called()


@pytest.mark.unit
class TestWebPush:
    def test_off_without_keys(self, monkeypatch):
        from modules import webpush
        monkeypatch.delenv("HERMES_VAPID_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("HERMES_VAPID_PRIVATE_KEY", raising=False)
        assert not webpush.configured()
        assert webpush.send_all(MagicMock(), {"title": "x"}) == 0

    def test_subscription_validated_and_stored(self):
        from modules import webpush
        archive = MagicMock()
        out = webpush.subscribe(archive, {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}})
        row = archive._route_archive.call_args.kwargs["body"]["rows"][0]
        assert row["kind"] == "push" and row["id"] == out["id"]
        with pytest.raises(ValueError):
            webpush.subscribe(archive, {"endpoint": "http://insecure", "keys": {}})

    def test_payload_is_plain_and_small(self):
        from modules import webpush
        p = webpush.payload_of({"notification_id": "n1", "title": "T", "message": "<b>ciao</b>" + "x" * 500,
                                "secret": {"fields": [{"name": "pin"}]}})
        assert p["body"].startswith("ciao") and len(p["body"]) == 300 and p["pending"] is True
        assert "secret" not in p

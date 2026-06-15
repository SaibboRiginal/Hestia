"""Comprehensive unit tests for Hecate gateway endpoints and provider lifecycle."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app.main as hecate_main
from app.main import app, _pending_auth


@pytest.fixture(autouse=True)
def clear_pending_auth():
    """Ensure _pending_auth is clean before and after every test."""
    _pending_auth.clear()
    yield
    _pending_auth.clear()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "hestia_hecate"


# ---------------------------------------------------------------------------
# detect_gateway_providers
# ---------------------------------------------------------------------------


def test_detect_providers_empty(monkeypatch):
    for key in [
        "GOOGLE_TOKEN_JSON", "GOOGLE_CREDENTIALS_JSON", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN", "OUTLOOK_CLIENT_ID", "OUTLOOK_CLIENT_SECRET",
        "OUTLOOK_TENANT_ID", "OUTLOOK_REFRESH_TOKEN",
        "HECATE_ENABLE_PROVIDER_GOOGLE", "HECATE_ENABLE_PROVIDER_MICROSOFT",
    ]:
        monkeypatch.delenv(key, raising=False)

    assert hecate_main.detect_gateway_providers() == []


def test_detect_providers_google_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "gtoken")

    providers = {row["provider"]: row for row in hecate_main.detect_gateway_providers()}
    assert "google" in providers
    assert providers["google"]["configured"] is True
    assert providers["google"]["auth_status"] == "configured"


def test_detect_providers_google_force_enabled(monkeypatch):
    for key in ["GOOGLE_TOKEN_JSON", "GOOGLE_CREDENTIALS_JSON", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HECATE_ENABLE_PROVIDER_GOOGLE", "true")

    providers = {row["provider"]: row for row in hecate_main.detect_gateway_providers()}
    assert "google" in providers
    assert providers["google"]["configured"] is False
    assert providers["google"]["enabled"] is True


def test_detect_providers_microsoft_configured(monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "mid")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "msecret")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant")
    monkeypatch.setenv("OUTLOOK_REFRESH_TOKEN", "mtoken")

    providers = {row["provider"]: row for row in hecate_main.detect_gateway_providers()}
    assert "microsoft" in providers
    assert providers["microsoft"]["configured"] is True


# ---------------------------------------------------------------------------
# /api/gateway/providers & /api/gateway/auth/status
# ---------------------------------------------------------------------------


def test_gateway_providers_endpoint(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "gtoken")

    resp = client.get("/api/gateway/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert "providers" in data
    assert "runtime" in data


def test_gateway_auth_status_endpoint(client, monkeypatch):
    for key in ["GOOGLE_TOKEN_JSON", "GOOGLE_CREDENTIALS_JSON", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                "GOOGLE_REFRESH_TOKEN", "OUTLOOK_CLIENT_ID", "OUTLOOK_CLIENT_SECRET",
                "OUTLOOK_TENANT_ID", "OUTLOOK_REFRESH_TOKEN"]:
        monkeypatch.delenv(key, raising=False)

    resp = client.get("/api/gateway/auth/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "providers" in data
    assert "runtime" in data


# ---------------------------------------------------------------------------
# /api/gateway/auth/refresh/{provider}
# ---------------------------------------------------------------------------


def test_gateway_auth_refresh_unsupported_provider(client):
    resp = client.post("/api/gateway/auth/refresh/facebook")
    assert resp.status_code == 400


def test_gateway_auth_refresh_unconfigured_provider(client, monkeypatch):
    for key in ["GOOGLE_TOKEN_JSON", "GOOGLE_CREDENTIALS_JSON", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("HECATE_ENABLE_PROVIDER_GOOGLE", raising=False)

    resp = client.post("/api/gateway/auth/refresh/google")
    assert resp.status_code == 200
    data = resp.json()
    assert data["refreshed"] is False
    assert data["reason"] == "provider_not_configured"


def test_gateway_auth_refresh_calls_provider_refresh(monkeypatch):
    """_refresh_calendar_registry should call refresh() on active providers."""
    mock_provider = MagicMock()
    mock_provider.refresh.return_value = True
    mock_provider.name = "google"

    monkeypatch.setattr(hecate_main._calendar_registry,
                        "_active", {"google": mock_provider})

    result = hecate_main._refresh_calendar_registry()

    mock_provider.refresh.assert_called_once()
    assert "google" in result.get("active", [])


def test_gateway_auth_refresh_fallback_when_no_active_providers(monkeypatch):
    """When no providers are active, registry is reinitialised."""
    # Save and restore _calendar_registry since _refresh_calendar_registry may replace it
    monkeypatch.setattr(hecate_main, "_calendar_registry",
                        hecate_main._calendar_registry)
    monkeypatch.setattr(hecate_main._calendar_registry, "_active", {})

    new_registry = MagicMock()
    new_registry.status_report.return_value = {"active": [], "unavailable": {}}
    with patch.object(hecate_main, "CalendarProviderRegistry", return_value=new_registry):
        result = hecate_main._refresh_calendar_registry()

    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# /api/gateway/calendar/events (GET)
# ---------------------------------------------------------------------------


def test_gateway_calendar_events_no_providers(client, monkeypatch):
    """When no providers are active and none explicitly requested, return empty."""
    monkeypatch.setattr(hecate_main._calendar_registry, "_active", {})
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])

    resp = client.get("/api/gateway/calendar/events")
    assert resp.status_code == 200
    data = resp.json()
    assert data["events"] == []


def test_gateway_calendar_events_with_mock_provider(monkeypatch):
    from app.main import gateway_calendar_events
    from app.schemas.calendar_events import CalendarEventRecord

    fake_event = CalendarEventRecord(
        provider="google",
        event_id="evt1",
        title="Test Event",
        start_datetime="2026-05-14T10:00:00Z",
        end_datetime="2026-05-14T11:00:00Z",
    )

    mock_provider = MagicMock()
    mock_provider.name = "google"
    mock_provider.list_events.return_value = [fake_event]

    monkeypatch.setattr(hecate_main._calendar_registry,
                        "_active", {"google": mock_provider})
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])

    result = gateway_calendar_events(
        start_datetime=None, end_datetime=None, provider=None,
        calendar_id="primary", max_results=10,
    )

    assert len(result["events"]) == 1
    assert result["events"][0]["title"] == "Test Event"
    assert result["provider_errors"] == {}


def test_gateway_calendar_events_unknown_provider(client, monkeypatch):
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])

    resp = client.get("/api/gateway/calendar/events?provider=nonexistent")
    assert resp.status_code == 404


def test_gateway_calendar_events_provider_error_is_captured(monkeypatch):
    from app.main import gateway_calendar_events

    mock_provider = MagicMock()
    mock_provider.name = "google"
    mock_provider.list_events.side_effect = RuntimeError("API timeout")

    monkeypatch.setattr(hecate_main._calendar_registry,
                        "_active", {"google": mock_provider})
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])

    result = gateway_calendar_events(
        start_datetime=None, end_datetime=None, provider=None,
        calendar_id="primary", max_results=10,
    )
    assert result["events"] == []
    assert "google" in result["provider_errors"]
    assert "API timeout" in result["provider_errors"]["google"]


# ---------------------------------------------------------------------------
# /api/gateway/calendar/events (POST - create)
# ---------------------------------------------------------------------------


def test_gateway_calendar_create_no_providers(client, monkeypatch):
    monkeypatch.setattr(hecate_main._calendar_registry, "_active", {})
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])

    body = {
        "event": {
            "title": "Test", "start_datetime": "2026-05-14T10:00:00Z",
            "end_datetime": "2026-05-14T11:00:00Z",
        }
    }
    resp = client.post("/api/gateway/calendar/events", json=body)
    assert resp.status_code == 503


def test_gateway_calendar_create_missing_event(client, monkeypatch):
    resp = client.post("/api/gateway/calendar/events",
                       json={"calendar_id": "primary"})
    assert resp.status_code == 400


def test_gateway_calendar_create_success(monkeypatch):
    from app.main import gateway_calendar_create

    mock_provider = MagicMock()
    mock_provider.name = "google"
    mock_provider.create_event.return_value = "new-event-id"

    monkeypatch.setattr(hecate_main._calendar_registry,
                        "_active", {"google": mock_provider})
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])
    monkeypatch.setattr(hecate_main.vault,
                        "ship_calendar_item", lambda item: True)

    result = gateway_calendar_create({
        "event": {
            "title": "Meeting", "start_datetime": "2026-05-14T10:00:00Z",
            "end_datetime": "2026-05-14T11:00:00Z",
        }
    })

    assert result["total_created"] == 1
    assert result["results"][0]["event_id"] == "new-event-id"
    assert result["results"][0]["success"] is True


def test_gateway_calendar_create_partial_failure(monkeypatch):
    from app.main import gateway_calendar_create

    mock_good = MagicMock()
    mock_good.name = "google"
    mock_good.create_event.return_value = "evt-ok"
    mock_bad = MagicMock()
    mock_bad.name = "outlook"
    mock_bad.create_event.side_effect = RuntimeError("Outlook quota exceeded")

    monkeypatch.setattr(hecate_main._calendar_registry,
                        "_active", {"google": mock_good, "outlook": mock_bad})
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "resolve", lambda targets: [])
    monkeypatch.setattr(hecate_main.vault,
                        "ship_calendar_item", lambda item: True)

    result = gateway_calendar_create({
        "event": {
            "title": "Meeting", "start_datetime": "2026-05-14T10:00:00Z",
            "end_datetime": "2026-05-14T11:00:00Z",
        }
    })

    assert result["total_created"] == 1
    assert result["total_failed"] == 1


# ---------------------------------------------------------------------------
# /api/gateway/calendar/events/{id} (DELETE)
# ---------------------------------------------------------------------------


def test_gateway_calendar_delete_unknown_provider(client, monkeypatch):
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "get", lambda name: None)
    resp = client.delete(
        "/api/gateway/calendar/events/evt-1?provider=nonexistent")
    assert resp.status_code == 404


def test_gateway_calendar_delete_success(monkeypatch):
    from app.main import gateway_calendar_delete

    mock_provider = MagicMock()
    mock_provider.delete_event.return_value = True
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "get", lambda name: mock_provider)

    result = gateway_calendar_delete("evt-1", provider="google")
    assert result["success"] is True


# ---------------------------------------------------------------------------
# /api/gateway/calendar/events/{id} (PUT)
# ---------------------------------------------------------------------------


def test_gateway_calendar_update_missing_provider(client):
    resp = client.put("/api/gateway/calendar/events/evt-1",
                      json={"updates": {"title": "New"}})
    assert resp.status_code == 400


def test_gateway_calendar_update_unknown_provider(client, monkeypatch):
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "get", lambda name: None)
    resp = client.put(
        "/api/gateway/calendar/events/evt-1",
        json={"provider": "google", "updates": {"title": "New"}},
    )
    assert resp.status_code == 404


def test_gateway_calendar_update_success(monkeypatch):
    from app.main import gateway_calendar_update

    mock_provider = MagicMock()
    mock_provider.update_event.return_value = True
    monkeypatch.setattr(hecate_main._calendar_registry,
                        "get", lambda name: mock_provider)

    result = gateway_calendar_update(
        "evt-1", {"provider": "google", "updates": {"title": "Updated"}})
    assert result["success"] is True


# ---------------------------------------------------------------------------
# _normalize_provider_name
# ---------------------------------------------------------------------------


def test_normalize_microsoft_to_outlook():
    assert hecate_main._normalize_provider_name("Microsoft") == "outlook"
    assert hecate_main._normalize_provider_name("microsoft") == "outlook"


def test_normalize_google():
    assert hecate_main._normalize_provider_name("google") == "google"
    assert hecate_main._normalize_provider_name("Google") == "google"


def test_normalize_none():
    assert hecate_main._normalize_provider_name(None) is None


# ---------------------------------------------------------------------------
# OAuth initiation endpoints
# ---------------------------------------------------------------------------


def test_auth_initiate_unsupported_provider(client):
    resp = client.post("/api/gateway/auth/initiate/facebook")
    assert resp.status_code == 400


def test_auth_initiate_google_missing_credentials(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    resp = client.post("/api/gateway/auth/initiate/google")
    assert resp.status_code in (400, 501)


def test_auth_initiate_microsoft_missing_credentials(client, monkeypatch):
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    monkeypatch.delenv("OUTLOOK_TENANT_ID", raising=False)

    resp = client.post("/api/gateway/auth/initiate/microsoft")
    assert resp.status_code in (400, 501)


def test_auth_poll_no_pending_flow(client):
    resp = client.get("/api/gateway/auth/poll/google")
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_pending_flow"


def test_auth_cancel_clears_session(client):
    _pending_auth["google"] = {
        "flow": MagicMock(), "auth_url": "http://example.com"}

    resp = client.delete("/api/gateway/auth/initiate/google")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert "google" not in _pending_auth


def test_auth_complete_google_no_pending_flow(client):
    resp = client.post("/api/gateway/auth/complete/google",
                       json={"code": "abc"})
    assert resp.status_code == 404


def test_auth_complete_google_missing_code(client):
    _pending_auth["google"] = {
        "flow": MagicMock(), "auth_url": "http://example.com"}

    resp = client.post("/api/gateway/auth/complete/google", json={})
    assert resp.status_code == 400


def test_auth_initiate_google_mocked(client, monkeypatch):
    """Google OAuth initiate with mocked Flow."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setattr(hecate_main, "_GOOGLE_LIBS_AVAILABLE", True)

    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = (
        "https://accounts.google.com/auth?...", {})

    with patch("app.main.Flow", mock_flow) if False else patch.dict("sys.modules", {}):
        # Directly test the helper to avoid import patching complexity
        fake_flow_cls = MagicMock()
        fake_flow_instance = MagicMock()
        fake_flow_instance.authorization_url.return_value = (
            "https://accounts.google.com/auth?x=y", {})
        fake_flow_cls.from_client_config.return_value = fake_flow_instance

        with patch("app.main._initiate_google_oauth") as mock_initiate:
            mock_initiate.return_value = {
                "status": "initiated",
                "provider": "google",
                "mode": "redirect",
                "auth_url": "https://accounts.google.com/auth?x=y",
                "instructions": "Open the auth_url...",
            }
            resp = client.post("/api/gateway/auth/initiate/google")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "initiated"
    assert data["provider"] == "google"


def test_auth_complete_google_token_stored(monkeypatch):
    """google_auth_complete should call flow.fetch_token and store GOOGLE_TOKEN_JSON."""
    mock_creds = MagicMock()
    mock_creds.token = "access-token"
    mock_creds.refresh_token = "refresh-token"
    mock_creds.token_uri = "https://oauth2.googleapis.com/token"
    mock_creds.client_id = "gid"
    mock_creds.client_secret = "gsecret"
    mock_creds.scopes = ["https://www.googleapis.com/auth/calendar"]

    mock_flow = MagicMock()
    mock_flow.credentials = mock_creds

    _pending_auth["google"] = {"flow": mock_flow,
                               "auth_url": "http://example.com"}
    monkeypatch.setattr(hecate_main, "_refresh_calendar_registry", lambda: {
                        "active": ["google"], "unavailable": {}})

    result = hecate_main._complete_google_oauth({"code": "auth-code-xyz"})

    mock_flow.fetch_token.assert_called_once_with(code="auth-code-xyz")
    assert result["status"] == "authorized"
    assert result["provider"] == "google"
    import json
    import os
    stored = json.loads(os.environ.get("GOOGLE_TOKEN_JSON", "{}"))
    assert stored.get("refresh_token") == "refresh-token"
    assert "google" not in _pending_auth


# ---------------------------------------------------------------------------
# /api/logs
# ---------------------------------------------------------------------------


def test_get_logs_endpoint(client):
    resp = client.get("/api/logs?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "hestia_hecate"
    assert "logs" in data

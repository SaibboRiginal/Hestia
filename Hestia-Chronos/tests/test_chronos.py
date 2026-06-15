"""Tests — Chronos calendar service (Phase 8)

Tests for Chronos schemas, health endpoint, and event schemas.
All external calendar provider calls are mocked.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Calendar event schemas
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCalendarEventSchema:
    def test_valid_event_creation(self):
        from schemas.events import CalendarEvent
        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            title="Doctor appointment",
            start_datetime=now,
            end_datetime=now + timedelta(hours=1),
        )
        assert event.title == "Doctor appointment"
        assert event.timezone == "Europe/Rome"
        assert event.all_day is False

    def test_event_defaults_reminder_30_minutes(self):
        from schemas.events import CalendarEvent
        now = datetime.now(timezone.utc)
        event = CalendarEvent(
            title="Meeting",
            start_datetime=now,
            end_datetime=now + timedelta(hours=1),
        )
        assert 30 in event.reminders_minutes_before

    def test_create_event_request_default_calendar_primary(self):
        from schemas.events import CalendarEvent, CreateEventRequest
        now = datetime.now(timezone.utc)
        req = CreateEventRequest(
            event=CalendarEvent(
                title="Test",
                start_datetime=now,
                end_datetime=now + timedelta(hours=1),
            )
        )
        assert req.calendar_id == "primary"
        assert req.target_providers == []

    def test_create_event_response_counts(self):
        from schemas.events import CreateEventResponse, ProviderEventResult
        resp = CreateEventResponse(
            results=[
                ProviderEventResult(provider="google",
                                    success=True, event_id="eid1"),
                ProviderEventResult(provider="microsoft",
                                    success=False, error="auth_failed"),
            ],
            total_created=1,
            total_failed=1,
        )
        assert resp.total_created == 1
        assert resp.total_failed == 1


# ─────────────────────────────────────────────────────────────────────────────
# Chronos health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestChronosHealth:
    def test_health_returns_200(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("core.hub_client.register_on_hub"), \
                patch("services.sync_worker.start", MagicMock()), \
                patch("services.notification_worker.start", MagicMock()), \
                patch("hestia_common.startup_utils.wait_for_http_ready"):
            from fastapi.testclient import TestClient
            import main as chronos_main
            client = TestClient(
                chronos_main.app, raise_server_exceptions=False)
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_status_ok(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("core.hub_client.register_on_hub"), \
                patch("services.sync_worker.start", MagicMock()), \
                patch("services.notification_worker.start", MagicMock()), \
                patch("hestia_common.startup_utils.wait_for_http_ready"):
            from fastapi.testclient import TestClient
            import main as chronos_main
            client = TestClient(
                chronos_main.app, raise_server_exceptions=False)
            body = client.get("/health").json()
        assert body.get("status") == "ok"
        assert "chronos" in body.get("service", "").lower()

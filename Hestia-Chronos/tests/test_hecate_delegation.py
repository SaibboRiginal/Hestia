"""Unit tests for Chronos Hub-routing delegation to Hecate."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import app.main as chronos_main


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_status={self.status_code}")

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# _route_hecate helper
# ---------------------------------------------------------------------------


def test_route_hecate_delegates_to_hub(monkeypatch):
    """_route_hecate should POST to Hub routing endpoint and unpack the payload."""
    captured = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["body"] = json
        return _FakeResponse(200, {"status_code": 200, "payload": {"events": []}})

    import requests
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("HUB_API_URL", "http://hestia_hub:19001/api")

    status_code, payload = chronos_main._route_hecate(
        method="GET",
        path="/api/gateway/calendar/events",
        query={"provider": "google"},
    )

    assert "hestia_hub" in captured["url"]
    assert "hecate" in captured["url"]
    assert status_code == 200
    assert payload == {"events": []}


def test_route_hecate_propagates_error_status(monkeypatch):
    import requests
    monkeypatch.setattr(
        requests, "post",
        lambda url, json, timeout: _FakeResponse(
            200, {"status_code": 503, "payload": {"detail": "unavailable"}}),
    )

    status_code, payload = chronos_main._route_hecate(
        method="GET", path="/api/gateway/calendar/events"
    )

    assert status_code == 503
    assert payload == {"detail": "unavailable"}


# ---------------------------------------------------------------------------
# create_event delegation
# ---------------------------------------------------------------------------


def test_create_event_delegates_to_hecate(monkeypatch):
    """POST /api/calendar/events should call _route_hecate with the gateway path."""
    from fastapi.testclient import TestClient

    calls = []

    def fake_route(*, method, path, body, timeout_seconds):
        calls.append({"method": method, "path": path, "body": body})
        return 200, {
            "results": [{"provider": "google", "success": True, "event_id": "evt-123", "error": None}],
            "total_created": 1,
            "total_failed": 0,
        }

    monkeypatch.setattr(chronos_main, "_route_hecate", fake_route)

    body = {
        "event": {
            "title": "Meeting",
            "start_datetime": "2026-05-14T10:00:00Z",
            "end_datetime": "2026-05-14T11:00:00Z",
        }
    }

    client = TestClient(chronos_main.app, raise_server_exceptions=True)
    resp = client.post("/api/calendar/events", json=body)

    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert "gateway/calendar/events" in calls[0]["path"]


# ---------------------------------------------------------------------------
# list_events delegation
# ---------------------------------------------------------------------------


def test_list_events_delegates_to_hecate(monkeypatch):
    calls = []

    def fake_route(*, method, path, query, timeout_seconds):
        calls.append({"method": method, "path": path, "query": query})
        return 200, {"events": [], "provider_errors": {}}

    monkeypatch.setattr(chronos_main, "_route_hecate", fake_route)

    from fastapi.testclient import TestClient
    client = TestClient(chronos_main.app, raise_server_exceptions=True)

    body = {
        "start_datetime": "2026-05-14T00:00:00Z",
        "end_datetime": "2026-05-21T00:00:00Z",
        "target_providers": ["google"],
    }
    resp = client.post("/api/calendar/events/list", json=body)

    assert len(calls) == 1
    assert calls[0]["method"] == "GET"
    assert "gateway/calendar/events" in calls[0]["path"]
    assert calls[0]["query"]["provider"] == "google"


# ---------------------------------------------------------------------------
# delete_event delegation
# ---------------------------------------------------------------------------


def test_delete_event_delegates_to_hecate(monkeypatch):
    calls = []

    def fake_route(*, method, path, query, timeout_seconds):
        calls.append({"method": method, "path": path})
        return 200, {"success": True}

    monkeypatch.setattr(chronos_main, "_route_hecate", fake_route)

    from app.schemas.events import DeleteEventRequest
    from fastapi.responses import JSONResponse

    result = chronos_main.delete_event(
        "evt-1", DeleteEventRequest(provider="google"))

    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert "evt-1" in calls[0]["path"]


# ---------------------------------------------------------------------------
# Hecate errors propagate as HTTPException
# ---------------------------------------------------------------------------


def test_create_event_propagates_hecate_error(monkeypatch):
    monkeypatch.setattr(
        chronos_main, "_route_hecate",
        lambda **kwargs: (503, {"detail": "No calendar providers available"}),
    )

    from fastapi.testclient import TestClient
    client = TestClient(chronos_main.app, raise_server_exceptions=False)

    body = {
        "event": {
            "title": "Meeting",
            "start_datetime": "2026-05-14T10:00:00Z",
            "end_datetime": "2026-05-14T11:00:00Z",
        }
    }
    resp = client.post("/api/calendar/events", json=body)
    assert resp.status_code == 503

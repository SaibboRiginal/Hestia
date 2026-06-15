"""Tests — Dummy service (Phase 14)

Tests for the Dummy service health endpoint and basic API contracts.
Dummy is the template service used to spin up new services.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


# ─────────────────────────────────────────────────────────────────────────────
# Dummy health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dummy_client():
    with patch("requests.post"), patch("requests.get"), \
            patch("hestia_common.startup_utils.wait_for_http_ready"):
        from fastapi.testclient import TestClient
        import main as dummy_main
        client = TestClient(dummy_main.app, raise_server_exceptions=False)
        yield client


@pytest.mark.api
class TestDummyHealth:
    def test_health_returns_200(self, dummy_client):
        resp = dummy_client.get("/health")
        assert resp.status_code == 200

    def test_health_body_status_ok(self, dummy_client):
        body = dummy_client.get("/health").json()
        assert body.get("status") == "ok"

    def test_health_body_has_service_field(self, dummy_client):
        body = dummy_client.get("/health").json()
        assert "service" in body


@pytest.mark.api
class TestDummyLogs:
    def test_logs_endpoint_returns_200(self, dummy_client):
        resp = dummy_client.get("/api/logs")
        assert resp.status_code == 200

    def test_logs_body_has_service_field(self, dummy_client):
        body = dummy_client.get("/api/logs").json()
        assert "service" in body
        assert "logs" in body

"""Tests — Argus health polling and alert service (Phase 10)

Tests for Argus health_poller, schemas, and API health endpoint.
All HTTP calls are mocked.
"""
from __future__ import annotations

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# HealthReport schema
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHealthReportSchema:
    def test_status_up(self):
        from schemas.reports import HealthReport
        r = HealthReport(service="oracle", status="up")
        assert r.status == "up"
        assert r.error is None

    def test_status_down_with_error(self):
        from schemas.reports import HealthReport
        r = HealthReport(service="oracle", status="down",
                         error="Connection refused")
        assert r.error == "Connection refused"

    def test_defaults_applied(self):
        from schemas.reports import HealthReport
        r = HealthReport(service="hub", status="up")
        assert isinstance(r.checked_at, datetime)
        assert r.details == {}


# ─────────────────────────────────────────────────────────────────────────────
# poll_service — unit test
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPollService:
    def test_200_response_returns_up(self, monkeypatch):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"status": "ok", "service": "oracle"}
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_resp)
        from core.health_poller import poll_service
        report = poll_service(
            {"name": "oracle", "base_url": "http://oracle:19004"})
        assert report.status == "up"
        assert report.service == "oracle"

    def test_non_200_returns_degraded(self, monkeypatch):
        fake_resp = MagicMock()
        fake_resp.status_code = 503
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_resp)
        from core.health_poller import poll_service
        report = poll_service(
            {"name": "archive", "base_url": "http://archive:19002"})
        assert report.status == "degraded"
        assert "503" in (report.error or "")

    def test_connection_error_returns_down(self, monkeypatch):
        import requests as req
        monkeypatch.setattr("requests.get", lambda *a, **kw: (_ for _ in ()
                                                              ).throw(req.exceptions.ConnectionError("refused")))
        from core.health_poller import poll_service
        report = poll_service(
            {"name": "hermes", "base_url": "http://hermes:19005"})
        assert report.status == "down"

    def test_poll_all_returns_dict(self, monkeypatch):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"status": "ok"}
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_resp)
        from core.health_poller import poll_all
        results = poll_all([
            {"name": "hub", "base_url": "http://hub:19001"},
            {"name": "oracle", "base_url": "http://oracle:19004"},
        ])
        assert "hub" in results
        assert "oracle" in results
        assert results["hub"].status == "up"


# ─────────────────────────────────────────────────────────────────────────────
# Argus health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestArgusHealth:
    def test_health_returns_200(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("core.hub_client.register"), \
                patch("core.hub_client.discover_services", return_value=[]), \
                patch("hestia_common.startup_utils.wait_for_http_ready"), \
                patch("core.context_loader.get_context", return_value=""):
            from fastapi.testclient import TestClient
            import main as argus_main
            client = TestClient(argus_main.app, raise_server_exceptions=False)
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_service_argus(self):
        with patch("requests.post"), patch("requests.get"), \
                patch("core.hub_client.register"), \
                patch("core.hub_client.discover_services", return_value=[]), \
                patch("hestia_common.startup_utils.wait_for_http_ready"), \
                patch("core.context_loader.get_context", return_value=""):
            from fastapi.testclient import TestClient
            import main as argus_main
            client = TestClient(argus_main.app, raise_server_exceptions=False)
            body = client.get("/health").json()
        assert "argus" in body.get("service", "").lower()

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


# ─────────────────────────────────────────────────────────────────────────────
# Daily recap piece (docs/work/2026-10-20-recap-giornaliero): reference module for the shared contract
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestDummyRecap:
    def test_quiet_day_is_empty(self, dummy_client):
        resp = dummy_client.get("/api/module/recap", params={"day": "2020-01-01"})
        assert resp.status_code == 200 and resp.json() == {"module": "dummy", "empty": True}

    def test_reconcile_today_is_in_the_piece(self, dummy_client):
        dummy_client.post("/api/module/maintenance/reconcile", json={"dry_run": False, "task_id": "t1"})
        body = dummy_client.get("/api/module/recap").json()
        assert body["module"] == "dummy" and body["title"] == "Prova"
        assert body["done"][0]["tone"] == "success" and "Riconciliazione" in body["done"][0]["text"]

    def test_bad_day_is_400(self, dummy_client):
        assert dummy_client.get("/api/module/recap", params={"day": "ieri"}).status_code == 400


@pytest.mark.unit
class TestRecapHelper:
    def test_piece_drops_empty_lines_and_lists(self):
        from hestia_common import recap
        p = recap.piece("x", "Area", done=["fatto", {"text": " "}], missed=[], next=None)
        assert p["done"] == [{"text": "fatto"}] and "missed" not in p and "next" not in p
        assert recap.piece("x", "Area") == {"module": "x", "empty": True}
        assert recap.is_empty({"module": "x", "empty": True}) and not recap.is_empty(p)

    def test_parse_days_defaults_to_day_after(self):
        from datetime import date
        from hestia_common import recap
        assert recap.parse_days("2026-10-20") == (date(2026, 10, 20), date(2026, 10, 21))
        assert recap.parse_days(today=date(2026, 12, 31))[1] == date(2027, 1, 1)

    def test_capability(self):
        from hestia_common import recap
        assert recap.capabilities() == {"recap_endpoint": "/api/module/recap"}

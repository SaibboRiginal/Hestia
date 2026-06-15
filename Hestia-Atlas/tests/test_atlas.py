"""Tests — Atlas HTML fetcher service (Phase 13)

Tests for Atlas schemas, health endpoint, and fetch response contracts.
No real browser/CDP calls — all mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestFetchHtmlSchemas:
    def test_request_defaults(self):
        from schemas import FetchHtmlRequest
        req = FetchHtmlRequest(url="https://example.com")
        assert req.timeout_seconds == 30
        assert req.wait_ms == 3000
        assert req.strategy == "edge_cdp"

    def test_request_custom_values(self):
        from schemas import FetchHtmlRequest
        req = FetchHtmlRequest(
            url="https://example.com/page",
            timeout_seconds=60,
            wait_ms=1000,
            strategy="cdp",
        )
        assert req.timeout_seconds == 60
        assert req.strategy == "cdp"

    def test_response_ok_status(self):
        from schemas import FetchHtmlResponse
        resp = FetchHtmlResponse(
            status="ok",
            url="https://example.com",
            html="<html></html>",
            content_length=14,
            fetch_method="edge_cdp",
        )
        assert resp.status == "ok"
        assert resp.blocked is False

    def test_response_error_status(self):
        from schemas import FetchHtmlResponse
        resp = FetchHtmlResponse(
            status="error",
            url="https://example.com",
            error="Timeout",
        )
        assert resp.status == "error"
        assert resp.error == "Timeout"


# ─────────────────────────────────────────────────────────────────────────────
# _is_blocked detection
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestIsBlocked:
    def test_captcha_delivery_marker_detected(self):
        from fetcher import _is_blocked
        assert _is_blocked("geo.captcha-delivery.com is the source") is True

    def test_ddblock_detected(self):
        from fetcher import _is_blocked
        assert _is_blocked("Some ddblock challenge page") is True

    def test_clean_page_not_blocked(self):
        from fetcher import _is_blocked
        assert _is_blocked("<html><body>Normal content</body></html>") is False

    def test_empty_string_not_blocked(self):
        from fetcher import _is_blocked
        assert _is_blocked("") is False


# ─────────────────────────────────────────────────────────────────────────────
# Atlas health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestAtlasHealth:
    def test_health_returns_200(self):
        with patch("requests.post"), patch("requests.get"):
            from fastapi.testclient import TestClient
            from app.main import app as atlas_app
            client = TestClient(atlas_app, raise_server_exceptions=False)
            resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_status_ok(self):
        with patch("requests.post"), patch("requests.get"):
            from fastapi.testclient import TestClient
            from app.main import app as atlas_app
            client = TestClient(atlas_app, raise_server_exceptions=False)
            body = client.get("/health").json()
        assert body.get("status") == "ok"
        assert "atlas" in body.get("service", "").lower()

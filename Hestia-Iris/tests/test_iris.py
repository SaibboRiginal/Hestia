"""Tests — Iris email gateway (Phase 9)

Tests for Iris service: health endpoint, email send schema validation,
inbox listing endpoint contracts.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────────────────
# Schema validation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestIrisEmailSchemas:
    def test_email_send_request_valid(self):
        from main import EmailSendRequest
        req = EmailSendRequest(
            to="user@example.com",
            subject="Test email",
            body="<b>Hello</b>",
        )
        assert req.to == "user@example.com"
        assert req.thread_id is None

    def test_email_send_request_with_thread_id(self):
        from main import EmailSendRequest
        req = EmailSendRequest(
            to="a@b.com",
            subject="Re: test",
            body="Reply body",
            thread_id="thread_abc123",
        )
        assert req.thread_id == "thread_abc123"


# ─────────────────────────────────────────────────────────────────────────────
# Iris health endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def iris_client():
    with patch("requests.post"), patch("requests.get"), \
            patch("hestia_common.startup_utils.wait_for_http_ready"):
        from fastapi.testclient import TestClient
        import main as iris_main
        client = TestClient(iris_main.app, raise_server_exceptions=False)
        yield client


@pytest.mark.api
class TestIrisHealth:
    def test_health_returns_200(self, iris_client):
        resp = iris_client.get("/health")
        assert resp.status_code == 200

    def test_health_body_ok(self, iris_client):
        body = iris_client.get("/health").json()
        assert body.get("status") == "ok"
        assert "iris" in body.get("service", "").lower()


@pytest.mark.api
class TestIrisMessagesEndpoint:
    def test_messages_list_returns_list(self, iris_client):
        resp = iris_client.get("/api/email/messages")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list) or isinstance(body.get("messages"), list)

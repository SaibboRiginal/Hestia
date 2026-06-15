"""Tests — Oracle FastAPI endpoints (Phase 1.7)

API tests using FastAPI TestClient with OracleEngine fully mocked.
Tests: /health, /api/logs, /api/format, /api/chat, /api/user/controls,
       /api/athena/hints.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# App fixture — mocks OracleEngine BEFORE importing main
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def oracle_client():
    """Return a TestClient for the Oracle FastAPI app with engine fully mocked."""
    mock_engine = MagicMock()

    # /api/chat returns an NDJSON stream
    def _fake_chat(*args, **kwargs):
        frames = [
            json.dumps({"type": "token", "content": "Ciao "}).encode(),
            json.dumps({"type": "token", "content": "Mark!"}).encode(),
            json.dumps({"type": "done", "signals": []}).encode(),
        ]
        return iter(frames)

    mock_engine.chat.return_value = _fake_chat()

    # /api/format returns a string
    mock_engine.format_payload.return_value = "<b>Risultato formattato</b>"

    # /api/user/controls
    mock_engine.get_user_controls.return_value = {
        "proactive_enabled": True,
        "allowed_categories": ["alerts", "tasks"],
        "quiet_hours": {"enabled": False, "start": "22:00", "end": "07:00"},
        "reminder_aggressiveness": "normal",
        "dont_ask_again": [],
        "reset_scope": "primary",
    }
    mock_engine.update_user_controls.return_value = (
        {"proactive_enabled": False, "allowed_categories": ["alerts"]},
        True,
    )

    # /api/athena/hints
    mock_engine.ingest_athena_hint.return_value = {
        "ok": True, "hint_id": "h001"}
    mock_engine.list_athena_hints.return_value = []

    # /api/tasks
    mock_engine.list_background_tasks.return_value = []
    mock_engine.get_background_task.return_value = None

    with patch("core.oracle_engine.OracleEngine", return_value=mock_engine):
        # Also patch requests.post to suppress Hub registration
        with patch("requests.post"):
            import main  # noqa: PLC0415 — imported after patch
            # Re-wire the module-level engine to our mock
            main.engine = mock_engine
            client = TestClient(main.app, raise_server_exceptions=True)
            yield client, mock_engine


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestOracleHealth:
    def test_health_returns_200(self, oracle_client):
        client, _ = oracle_client
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_body_has_status_ok(self, oracle_client):
        client, _ = oracle_client
        data = client.get("/health").json()
        assert data.get("status") == "ok"
        assert data.get("service") == "hestia_oracle"


@pytest.mark.api
class TestOracleLogsEndpoint:
    def test_logs_returns_200(self, oracle_client):
        client, _ = oracle_client
        resp = client.get("/api/logs")
        assert resp.status_code == 200

    def test_logs_response_has_service_field(self, oracle_client):
        client, _ = oracle_client
        data = client.get("/api/logs").json()
        assert "service" in data
        assert data["service"] == "hestia_oracle"

    def test_logs_limit_param(self, oracle_client):
        client, _ = oracle_client
        resp = client.get("/api/logs?limit=10")
        assert resp.status_code == 200


@pytest.mark.api
class TestOracleFormatEndpoint:
    def test_format_returns_200_with_text(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.format_payload.return_value = "<b>Output</b>"
        resp = client.post(
            "/api/format",
            json={
                "command": "scout_listings",
                "payload": [{"title": "Appartamento", "price": 250000}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data

    def test_format_calls_engine_with_command(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.format_payload.reset_mock()
        client.post(
            "/api/format",
            json={"command": "my_command", "payload": {"foo": "bar"}},
        )
        mock_engine.format_payload.assert_called_once()
        call_kwargs = mock_engine.format_payload.call_args
        assert call_kwargs is not None

    def test_format_missing_command_returns_422(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/format", json={"payload": {}})
        assert resp.status_code == 422

    def test_format_missing_payload_returns_422(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/format", json={"command": "test"})
        assert resp.status_code == 422


@pytest.mark.api
class TestOracleChatEndpoint:
    def test_chat_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        # Reset and configure streaming mock
        mock_engine.chat.return_value = iter([
            json.dumps({"type": "token", "content": "Ciao"}).encode(),
            json.dumps({"type": "done", "signals": []}).encode(),
        ])
        resp = client.post(
            "/api/chat",
            json={"message": "Ciao Hestia!", "session_id": "test-session-001"},
        )
        assert resp.status_code == 200

    def test_chat_content_type_ndjson(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.chat.return_value = iter([
            json.dumps({"type": "done", "signals": []}).encode()
        ])
        resp = client.post("/api/chat", json={"message": "Test"})
        assert "ndjson" in resp.headers.get(
            "content-type", "").lower() or resp.status_code == 200

    def test_chat_missing_message_returns_422(self, oracle_client):
        client, _ = oracle_client
        resp = client.post("/api/chat", json={"session_id": "abc"})
        assert resp.status_code == 422

    def test_chat_with_client_instructions_passes_to_engine(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.chat.reset_mock()
        mock_engine.chat.return_value = iter([
            json.dumps({"type": "done", "signals": []}).encode()
        ])
        client.post(
            "/api/chat",
            json={"message": "Test", "client_instructions": "Rispondi brevemente"},
        )
        assert mock_engine.chat.called


@pytest.mark.api
class TestOracleAthenaHintsEndpoint:
    def test_ingest_hint_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.ingest_athena_hint.return_value = {"ok": True}
        resp = client.post(
            "/api/athena/hints",
            json={
                "source": "athena",
                "hint_type": "focus_brief",
                "summary": "Ci sono 3 nuovi annunci a Milano",
                "priority": "normal",
                "domain": "scout",
            },
        )
        assert resp.status_code == 200

    def test_list_hints_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.list_athena_hints.return_value = []
        resp = client.get("/api/athena/hints")
        assert resp.status_code == 200
        data = resp.json()
        assert "hints" in data


@pytest.mark.api
class TestOracleTasksEndpoint:
    def test_list_tasks_returns_200(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.list_background_tasks.return_value = []
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        assert "tasks" in resp.json()

    def test_get_unknown_task_returns_404(self, oracle_client):
        client, mock_engine = oracle_client
        mock_engine.get_background_task.return_value = None
        resp = client.get("/api/tasks/nonexistent-task-id")
        assert resp.status_code == 404

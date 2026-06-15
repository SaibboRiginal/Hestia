"""Tests — Telegram control API (Phase 2.5)

Tests for the HTTP control service (GET /health, GET /api/logs,
POST /api/events/registry-changed, POST /api/dispatch/send).
Uses a minimal threaded server spin-up.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import ThreadingHTTPServer
from io import BytesIO
from unittest.mock import MagicMock, patch
import pytest

# conftest adds app/ to sys.path and patches telebot + sets env vars


# ─────────────────────────────────────────────────────────────────────────────
# Minimal test client for the ControlRequestHandler
# ─────────────────────────────────────────────────────────────────────────────


class _FakeRFile:
    """Minimal read-only file-like for simulating HTTP body."""

    def __init__(self, body: bytes = b""):
        self._buf = BytesIO(body)

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


class _FakeWFile:
    """Captures written bytes."""

    def __init__(self):
        self.written = BytesIO()

    def write(self, data: bytes):
        self.written.write(data)

    def flush(self):
        pass


class _FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeRequestHandler:
    """Drive ControlRequestHandler without a real socket."""

    def __init__(self, path: str, method: str = "GET", body: bytes = b""):
        from telegram_bot.services.control_service import ControlRequestHandler

        self._handler_cls = ControlRequestHandler
        self.path = path
        self.method = method
        self.body = body
        self.headers = _FakeHeaders({"Content-Length": str(len(body))})
        self._responses: list[tuple[int, dict]] = []

    def _run(self):
        handler = object.__new__(self._handler_cls)
        handler.path = self.path
        handler.headers = self.headers
        handler.rfile = _FakeRFile(self.body)
        handler.wfile = _FakeWFile()

        captured: list[tuple[int, dict]] = []

        def _fake_send_json(status_code: int, payload: dict):
            captured.append((status_code, payload))

        handler._send_json = _fake_send_json

        if self.method == "GET":
            handler.do_GET()
        elif self.method == "POST":
            handler.do_POST()

        self._responses = captured

    def response(self) -> tuple[int, dict]:
        self._run()
        if self._responses:
            return self._responses[0]
        return (0, {})


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.api
class TestControlApiHealth:
    def test_get_health_returns_200_ok(self, monkeypatch):
        import telegram_bot.core as core_module
        core_module.LOG_BUFFER = MagicMock()
        core_module.LOG_BUFFER.query.return_value = []
        handler = _FakeRequestHandler("/health", method="GET")
        status, body = handler.response()
        assert status == 200
        assert body.get("status") == "ok"

    def test_get_health_service_name_is_telegram(self, monkeypatch):
        handler = _FakeRequestHandler("/health", method="GET")
        _, body = handler.response()
        assert body.get("service") == "telegram"


@pytest.mark.api
class TestControlApiLogs:
    def test_get_logs_returns_200(self, monkeypatch):
        import telegram_bot.core as core_module
        core_module.LOG_BUFFER = MagicMock()
        core_module.LOG_BUFFER.query.return_value = [
            {"level": "INFO", "message": "test log", "ts": "2025-01-01T00:00:00"}
        ]
        handler = _FakeRequestHandler("/api/logs", method="GET")
        status, body = handler.response()
        assert status == 200

    def test_get_logs_body_has_service_field(self, monkeypatch):
        import telegram_bot.core as core_module
        core_module.LOG_BUFFER = MagicMock()
        core_module.LOG_BUFFER.query.return_value = []
        handler = _FakeRequestHandler("/api/logs", method="GET")
        _, body = handler.response()
        assert body.get("service") == "hestia_telegram"
        assert "logs" in body

    def test_get_unknown_path_returns_404(self):
        handler = _FakeRequestHandler("/api/nonexistent", method="GET")
        status, _ = handler.response()
        assert status == 404


@pytest.mark.api
class TestControlApiRegistryChanged:
    def test_registry_changed_returns_ok(self, monkeypatch):
        monkeypatch.setattr(
            "telegram_bot.services.control_service.refresh_command_registry",
            lambda force=True: None,
        )
        import telegram_bot.core as core_module
        core_module.COMMAND_REGISTRY_REVISION = 5
        handler = _FakeRequestHandler(
            "/api/events/registry-changed", method="POST", body=b"")
        status, body = handler.response()
        assert status == 200
        assert body.get("status") == "ok"


@pytest.mark.api
class TestControlApiDispatchSend:
    def test_send_message_with_valid_target(self, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        core_module.LOG_BUFFER = MagicMock()
        core_module.LOG_BUFFER.query.return_value = []

        payload = json.dumps({
            "target": "12345",
            "message": "<b>Notifica</b>: evento importante",
            "parse_mode": "HTML",
        }).encode()

        handler = _FakeRequestHandler(
            "/api/dispatch/send", method="POST", body=payload)
        status, body = handler.response()
        assert status == 200

    def test_send_message_missing_target_returns_error(self, monkeypatch):
        import telegram_bot.core as core_module
        mock_bot = MagicMock()
        core_module.bot = mock_bot

        payload = json.dumps({"text": "No target"}).encode()
        handler = _FakeRequestHandler(
            "/api/dispatch/send", method="POST", body=payload)
        status, _ = handler.response()
        # Missing or empty target should return 400
        assert status in (400, 422)

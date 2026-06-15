"""Tests — bot handler functions (Phase 2.3)

Unit tests for Telegram bot handler logic: authorization, welcome,
chat handling, callback routing. All bot API calls mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# is_authorized
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestIsAuthorized:
    def test_no_allowed_user_id_allows_everyone(self, fake_message, monkeypatch):
        monkeypatch.setenv("ALLOWED_USER_ID", "")
        # Re-import core so env var is picked up
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""
        from telegram_bot.services.chat_service import is_authorized
        msg = fake_message(text="/start")
        assert is_authorized(msg) is True

    def test_authorized_user_id_allowed(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = "99999"
        from telegram_bot.services.chat_service import is_authorized
        msg = fake_message(text="/start", user_id=99999)
        assert is_authorized(msg) is True

    def test_unauthorized_user_id_blocked(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = "11111"
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        from telegram_bot.services.chat_service import is_authorized
        msg = fake_message(text="/start", user_id=99999)
        result = is_authorized(msg)
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# send_welcome
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSendWelcome:
    def test_send_welcome_replies_to_message(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""  # allow all
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        monkeypatch.setattr("telegram_bot.services.registry.requests.get",
                            lambda *a, **kw: MagicMock(status_code=404, json=lambda: {}))
        from telegram_bot.services.chat_service import send_welcome
        msg = fake_message(text="/start")
        send_welcome(msg)
        mock_bot.reply_to.assert_called_once()

    def test_send_welcome_uses_html_parse_mode(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        monkeypatch.setattr("telegram_bot.services.registry.requests.get",
                            lambda *a, **kw: MagicMock(status_code=404, json=lambda: {}))
        from telegram_bot.services.chat_service import send_welcome
        msg = fake_message(text="/start")
        send_welcome(msg)
        _, kwargs = mock_bot.reply_to.call_args
        assert kwargs.get("parse_mode") == "HTML"

    def test_send_welcome_unauthorized_user_not_welcomed(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = "00000"  # different from test user 99999
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        from telegram_bot.services.chat_service import send_welcome
        msg = fake_message(text="/start", user_id=99999)
        send_welcome(msg)
        # reply_to is called once in is_authorized (access denied), not with welcome
        all_calls = [str(c) for c in mock_bot.reply_to.call_args_list]
        # Should not contain "Hestia pronta"
        for c in all_calls:
            assert "Hestia pronta" not in c


# ─────────────────────────────────────────────────────────────────────────────
# handle_chat_message (core oracle streaming)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandleChatMessage:
    def _setup(self, monkeypatch, frames: list[dict] | None = None):
        """Patch core.bot and oracle streaming for handle_chat_message tests."""
        import telegram_bot.core as core_module
        import json

        core_module.ALLOWED_USER_ID = ""
        mock_bot = MagicMock()
        core_module.bot = mock_bot

        _frames = frames or [
            {"type": "token", "content": "Ciao "},
            {"type": "token", "content": "Mark!"},
            {"type": "done", "signals": []},
        ]

        class _FakeStream:
            status_code = 200
            ok = True

            def iter_lines(self, **kwargs):
                for f in _frames:
                    yield json.dumps(f).encode()

            def raise_for_status(self):
                pass

        monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeStream())
        monkeypatch.setattr("requests.get",
                            lambda *a, **kw: MagicMock(status_code=404, json=lambda: {}))
        return mock_bot

    def test_chat_message_sends_reply_to_user(self, fake_message, monkeypatch):
        mock_bot = self._setup(monkeypatch)
        from telegram_bot.services.chat_service import handle_chat_message
        msg = fake_message(text="Ciao Hestia")
        with patch("session_store.get_session", return_value="session-001"), \
                patch("session_store.build_client_instructions_for_chat", return_value=""):
            handle_chat_message(msg)
        # Bot should have sent at least one message
        assert mock_bot.send_message.called or mock_bot.reply_to.called

    def test_chat_message_uses_html_parse_mode(self, fake_message, monkeypatch):
        mock_bot = self._setup(monkeypatch)
        from telegram_bot.services.chat_service import handle_chat_message
        msg = fake_message(text="Dimmi qualcosa")
        with patch("session_store.get_session", return_value="session-001"), \
                patch("session_store.build_client_instructions_for_chat", return_value=""):
            handle_chat_message(msg)
        for send_call in mock_bot.send_message.call_args_list:
            _, kwargs = send_call
            if kwargs.get("parse_mode"):
                assert kwargs["parse_mode"] == "HTML"


# ─────────────────────────────────────────────────────────────────────────────
# handle_confirmation callback
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandleConfirmation:
    def test_confirm_token_triggers_command_execution(self, fake_callback, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        token = "abc123"
        fake_pending = {
            token: {
                "command_name": "meteo",
                "command_metadata": {
                    "command": "meteo",
                    "method": "GET",
                    "path": "/api/meteo",
                    "response_mode": "direct",
                    "title": "Meteo",
                },
                "args": {},
            }
        }
        core_module.PENDING_CONFIRMATIONS = fake_pending
        cb = fake_callback(
            data=f"confirm:{token}", message=fake_message(text=""))

        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"temperature": "22°C"}
        monkeypatch.setattr("requests.get", lambda *a, **kw: fake_resp)
        monkeypatch.setattr("requests.post", lambda *a, **kw: fake_resp)

        from telegram_bot.services.chat_service import handle_confirmation
        handle_confirmation(cb)
        # The confirmation token should have been consumed (removed from pending)
        assert token not in core_module.PENDING_CONFIRMATIONS

    def test_cancel_token_removes_pending_confirmation(self, fake_callback, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        core_module.ALLOWED_USER_ID = ""
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        token = "xyz789"
        core_module.PENDING_CONFIRMATIONS = {token: {"command_name": "test"}}
        cb = fake_callback(
            data=f"cancel:{token}", message=fake_message(text=""))
        from telegram_bot.services.chat_service import handle_confirmation
        handle_confirmation(cb)
        assert token not in core_module.PENDING_CONFIRMATIONS


# ─────────────────────────────────────────────────────────────────────────────
# Session store
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSessionStore:
    def test_get_session_creates_uuid_for_new_chat(self, tmp_path):
        import session_store
        state_file = str(tmp_path / "sessions.json")
        session_id = session_store.get_session(state_file, "chat_42")
        assert len(session_id) == 36  # UUID format
        import re
        assert re.match(r"[0-9a-f-]{36}", session_id)

    def test_get_session_same_chat_same_id(self, tmp_path):
        import session_store
        state_file = str(tmp_path / "sessions.json")
        s1 = session_store.get_session(state_file, "chat_42")
        s2 = session_store.get_session(state_file, "chat_42")
        assert s1 == s2

    def test_reset_session_changes_id(self, tmp_path):
        import session_store
        state_file = str(tmp_path / "sessions.json")
        old = session_store.get_session(state_file, "chat_42")
        session_store.reset_session(state_file, "chat_42")
        new = session_store.get_session(state_file, "chat_42")
        assert old != new

    def test_different_chats_get_different_sessions(self, tmp_path):
        import session_store
        state_file = str(tmp_path / "sessions.json")
        s1 = session_store.get_session(state_file, "chat_1")
        s2 = session_store.get_session(state_file, "chat_2")
        assert s1 != s2

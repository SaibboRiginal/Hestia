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
    def test_no_allowed_user_id_denies_everyone(self, fake_message, monkeypatch):
        """Fail closed: the bot can command Forge, so no id configured = nobody."""
        import telegram_bot.core as core_module
        monkeypatch.setattr(core_module, "ALLOWED_USER_ID", "")
        monkeypatch.setattr(core_module, "bot", MagicMock())
        from telegram_bot.services.chat_service import is_authorized
        msg = fake_message(text="/start")
        assert is_authorized(msg) is False

    def test_multiple_allowed_ids(self, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        monkeypatch.setattr(core_module, "ALLOWED_USER_ID", "11111, 99999")
        from telegram_bot.services.chat_service import is_authorized
        assert is_authorized(fake_message(text="/start", user_id=99999)) is True

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
# Home (/start)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHome:
    def _home(self, monkeypatch):
        import telegram_bot.core as core_module
        from telegram_bot import catalog, nav
        from telegram_bot.menu import model
        core_module.ALLOWED_USER_ID = "99999"
        mock_bot = MagicMock()
        core_module.bot = mock_bot
        monkeypatch.setattr(catalog, "route", lambda *a, **kw: (True, {"unread": 2}))
        monkeypatch.setattr(catalog, "get", lambda name: None)
        monkeypatch.setattr(model, "current", lambda: model.build([], {}))
        nav.home(12345)
        return mock_bot

    def test_home_sends_greeting_with_bottom_keyboard(self, monkeypatch):
        bot = self._home(monkeypatch)
        args, kwargs = bot.send_message.call_args
        assert kwargs["parse_mode"] == "HTML"
        assert args[1].startswith("<b>Ciao</b>")
        assert "2 notifiche da vedere" in args[1]
        keys = [b["text"] for row in kwargs["reply_markup"].keyboard for b in row]
        assert keys == ["Oggi", "Aree", "Notifiche", "Impostazioni"]

    def test_start_command_opens_home(self, fake_message, monkeypatch):
        import telegram_runtime
        from telegram_bot import nav
        from telegram_bot.menu import model
        monkeypatch.setattr(model, "current", lambda: model.build([], {}))
        with patch.object(nav, "home") as home:
            telegram_runtime.on_message(fake_message(text="/start"))
        home.assert_called_once_with(12345)

    def test_keyboard_words_open_their_door_not_the_chat(self, fake_message, monkeypatch):
        import telegram_runtime
        from telegram_bot import nav
        from telegram_bot.menu import model
        monkeypatch.setattr(model, "current", lambda: model.build([], {}))
        with patch.object(nav, "open_door", return_value=True) as door, \
                patch("telegram_bot.services.chat_service.handle_chat_message") as chat:
            telegram_runtime.on_message(fake_message(text="Aree"))
            telegram_runtime.on_message(fake_message(text="mostrami le aree"))
        door.assert_called_once_with(12345, "aree")
        chat.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# handle_chat_message (core oracle streaming)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandleChatMessage:
    def _setup(self, monkeypatch, frames: list[dict] | None = None):
        """Patch core.bot and oracle streaming for handle_chat_message tests."""
        import telegram_bot.core as core_module
        import json

        core_module.ALLOWED_USER_ID = "99999"
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
# handle_confirmation callback (persisted tokens)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHandleConfirmation:
    def test_module_question_answer_goes_to_oracle(self, fake_callback, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        from telegram_bot import store
        core_module.bot = MagicMock()
        store.put_pending("abc123", {"action": "oracle_question", "chat_id": "12345", "session_id": "s",
                                     "question_id": "q1", "confirm": "yes", "cancel": "no",
                                     "labels": ["Applica", "Lascia stare"]})
        sent = []
        monkeypatch.setattr(core_module, "oracle_post",
                            lambda path, body, **kw: sent.append((path, body)) or (200, {"action": {"ok": True}}))
        from telegram_bot.services.chat_service import handle_confirmation
        handle_confirmation(fake_callback(data="confirm:abc123", message=fake_message(text="")))
        assert sent[0][0] == "api/chat/question-answer" and sent[0][1]["answer"] == "yes"
        assert store.get_pending("abc123") is None

    def test_failed_answer_keeps_the_token(self, fake_callback, fake_message, monkeypatch):
        import telegram_bot.core as core_module
        from telegram_bot import store
        core_module.bot = MagicMock()
        store.put_pending("xyz789", {"action": "oracle_question", "chat_id": "12345", "session_id": "s",
                                     "question_id": "q1", "confirm": "yes", "cancel": "no", "labels": ["Sì", "No"]})
        monkeypatch.setattr(core_module, "oracle_post", lambda *a, **kw: (0, {}))
        from telegram_bot.services.chat_service import handle_confirmation
        handle_confirmation(fake_callback(data="cancel:xyz789", message=fake_message(text="")))
        assert store.get_pending("xyz789") is not None

    def test_unknown_token_says_closed(self, fake_callback, fake_message):
        import telegram_bot.core as core_module
        core_module.bot = MagicMock()
        from telegram_bot.services.chat_service import handle_confirmation
        handle_confirmation(fake_callback(data="confirm:nope", message=fake_message(text="")))
        core_module.bot.answer_callback_query.assert_called_with("cb_001", "Questa richiesta è già chiusa")


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

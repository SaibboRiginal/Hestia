"""Voice on Telegram (docs/work/2026-10-20-modulo-voce §7): a voice note is a chat message, «Ascolta» under
replies, /live answers voice notes by voice, fallback to the document path when listening fails."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class _Voice:
    def __init__(self, heard="aggiungi al diario che ho dormito male"):
        self.heard, self.spoken, self.calls = heard, {"audio": b"OGG", "duration_s": 2.0}, []

    def transcribe(self, audio, mime, **kw):
        self.calls.append(("t", mime, kw))
        return {"text": self.heard} if self.heard else None

    def speak(self, text, **kw):
        self.calls.append(("s", text, kw))
        return self.spoken


@pytest.fixture
def env(monkeypatch):
    import telegram_bot.core as core_module
    from telegram_bot.services import voice_service
    core_module.ALLOWED_USER_ID = "99999"
    bot = MagicMock()
    bot.reply_to.return_value = MagicMock(message_id=50)
    core_module.bot = bot
    voice = _Voice()
    monkeypatch.setattr(voice_service, "_client", voice)
    settings: dict = {}
    monkeypatch.setattr(core_module, "get_session_settings", lambda chat: dict(settings))
    monkeypatch.setattr(core_module, "set_session_setting", lambda chat, k, v: settings.__setitem__(k, v))
    monkeypatch.setattr(core_module, "get_session", lambda chat: "s-1")
    oracle_calls = []

    class _Stream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self, **kw):
            yield json.dumps({"type": "final", "reply": "Segnato nel diario."}).encode()

        def raise_for_status(self):
            pass

    def post(url, json=None, **kw):
        oracle_calls.append(json)
        return _Stream()

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("telegram_bot.services.chat_service._download_telegram_file", lambda fid: b"OGGDATA")
    monkeypatch.setattr(core_module, "build_client_instructions_for_chat", lambda chat: "")
    return bot, voice, oracle_calls, settings


def _voice_message(fake_message):
    msg = fake_message(text=None, chat_id=12345, message_id=7)
    msg.content_type = "voice"
    msg.voice = MagicMock(file_id="f1", mime_type="audio/ogg")
    msg.caption = None
    return msg


@pytest.mark.unit
def test_voice_note_becomes_chat_message_with_listen_button(env, fake_message):
    bot, voice, oracle_calls, _ = env
    from telegram_bot.services.chat_service import handle_file_message
    handle_file_message(_voice_message(fake_message))
    assert oracle_calls[0]["message"] == "aggiungi al diario che ho dormito male"
    t = voice.calls[0]
    assert t[1] == "audio/ogg" and t[2]["use_case"] == "telegram.vocale" and t[2]["keep"]["kind"] == "recording"
    assert t[2]["keep"]["message_id"] == "tg:12345:7"
    assert "🎙️" in bot.edit_message_text.call_args_list[0][0][0]
    assert bot.edit_message_reply_markup.called and not bot.send_voice.called      # chat: text only


@pytest.mark.unit
def test_live_mode_answers_voice_notes_by_voice(env, fake_message):
    bot, voice, _, settings = env
    from telegram_bot.services import voice_service
    from telegram_bot.services.chat_service import handle_file_message
    assert "live" in voice_service.set_live(12345, True).lower()
    handle_file_message(_voice_message(fake_message))
    spoken = [c for c in voice.calls if c[0] == "s"]
    assert spoken[0][1] == "Segnato nel diario." and spoken[0][2]["fmt"] == "ogg_opus"
    assert bot.send_voice.called
    voice_service.set_live(12345, False)
    assert not voice_service.is_live(12345)


@pytest.mark.unit
def test_not_heard_falls_back_to_document_path(env, fake_message):
    _, voice, _, _ = env
    voice.heard = None
    with patch("telegram_bot.services.chat_service.handle_file_as_document") as doc:
        from telegram_bot.services.chat_service import handle_file_message
        handle_file_message(_voice_message(fake_message))
    assert doc.called


@pytest.mark.unit
def test_listen_button_speaks_the_reply(env, fake_callback):
    bot, voice, _, _ = env
    from telegram_bot.services import voice_service
    voice_service.remember_answer(12345, 60, "Risposta da leggere")
    call = fake_callback(voice_service.LISTEN_CALLBACK)
    call.message.chat.id, call.message.message_id = 12345, 60
    voice_service.handle_listen_callback(call)
    assert voice.calls[-1][1] == "Risposta da leggere" and voice.calls[-1][2]["keep"]["message_id"] == "tg:12345:60"
    assert bot.send_voice.called
    voice.spoken = None
    voice_service.handle_listen_callback(call)
    assert voice_service.CANT_SPEAK in bot.send_message.call_args[0][1]


@pytest.mark.unit
def test_voice_uses_in_registration():
    from telegram_bot.services.voice_service import capabilities
    ids = {u["id"]: u["direction"] for u in capabilities()["voice_usecases"]}
    assert ids == {"telegram.vocale": "ascolto", "telegram.risposta": "voce"}

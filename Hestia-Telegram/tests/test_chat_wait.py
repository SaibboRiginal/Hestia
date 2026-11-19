"""One answer at a time per chat; texts written meanwhile wait, «Add now» (dossier 2026-11-18-problemi-del-test B)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def wait(monkeypatch):
    import telegram_bot.core as core_module
    from telegram_bot.services import chat_wait
    bot = MagicMock()
    bot.reply_to.return_value = SimpleNamespace(message_id=500)
    monkeypatch.setattr(core_module, "bot", bot)
    chat_wait._busy.clear()
    yield chat_wait, bot
    chat_wait._busy.clear()


@pytest.mark.unit
def test_text_written_while_answering_goes_next_with_the_others(wait, monkeypatch):
    chat_wait, _ = wait
    from telegram_bot import core
    from telegram_bot.services import chat_service
    monkeypatch.setattr(core, "get_session", lambda chat_id: "s1")
    sent: list[str] = []

    def one_turn(message, chat_id, text, **_):
        sent.append(text)
        if len(sent) == 1:   # the owner writes twice while the first answer runs
            chat_service.run_chat_turn(SimpleNamespace(message_id=2), chat_id, "and tomorrow?")
            chat_service.run_chat_turn(SimpleNamespace(message_id=3), chat_id, "in Rome")
        return []

    monkeypatch.setattr(chat_service, "_one_turn", one_turn)
    chat_service.run_chat_turn(SimpleNamespace(message_id=1), 42, "weather today?")
    assert sent == ["weather today?", "and tomorrow?\n\nin Rome"]
    assert chat_wait._busy == {}


@pytest.mark.unit
def test_add_now_hands_the_text_to_the_running_answer(wait, monkeypatch):
    chat_wait, bot = wait
    from telegram_bot import core
    calls = []
    monkeypatch.setattr(core, "oracle_post", lambda path, body, timeout=15: (calls.append((path, body)) or
                                                                             (200, {"accepted": True})))
    assert chat_wait.start(42, "s1")
    assert chat_wait.hold(SimpleNamespace(message_id=2), 42, "and tomorrow?")
    item = chat_wait._busy["42"]["held"][0]
    call = SimpleNamespace(id="c1", data=f"cw:{item['id']}",
                           message=SimpleNamespace(chat=SimpleNamespace(id=42), message_id=500))
    chat_wait.handle_callback(call)
    assert calls == [("api/chat/steer", {"session_id": "s1", "text": "and tomorrow?", "id": item["id"]})]
    # taken by the answer: nothing goes next
    assert chat_wait.finish(42, [{"event": "chat.steer_taken", "data": {"ids": [item["id"]]}}]) == []
    assert chat_wait._busy == {}


@pytest.mark.unit
def test_added_but_not_taken_still_goes_next(wait):
    chat_wait, _ = wait
    chat_wait.start(42, "s1")
    chat_wait.hold(None, 42, "late text")
    chat_wait._busy["42"]["held"][0]["sent"] = True
    left = chat_wait.finish(42, [])
    assert [h["text"] for h in left] == ["late text"]
    assert chat_wait.finish(42, []) == []          # the next turn ended with nothing held: the chat is free
    assert chat_wait.start(42, "s1")

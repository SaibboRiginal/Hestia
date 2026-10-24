"""Questions the assistant asks in the chat (docs/work/2026-10-19-oracle-offline v3 A)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def env(monkeypatch, _ui_store):
    import telegram_bot.core as core
    core.ALLOWED_USER_ID = "99999"
    core.bot = MagicMock()
    posted = []

    def oracle_post(path, body, timeout=15, trace_id=None):
        posted.append((path, body))
        return 200, {"resolved": True, "resume": {"message": "Risposta alla tua domanda «Q»: " + body["answer"]}}

    monkeypatch.setattr(core, "oracle_post", oracle_post)
    return core, posted


def _call(data, chat_id=12345):
    return MagicMock(data=data, id="cb", message=MagicMock(chat=MagicMock(id=chat_id), message_id=50,
                                                            html_text="<b>Scegli</b>", text="Scegli"))


def _token(core):
    from telegram_bot import store
    return next(iter(store._load()["pending"]))


def _menu():
    from telegram_bot.menu import model
    return model.build([], {})


@pytest.mark.unit
def test_single_choice_answers_and_resumes(env):
    core, posted = env
    from telegram_bot.services import assistant_questions as aq
    aq.send(12345, "s-1", {"question_id": "ask_1", "header": "Scegli", "kind": "single_choice",
                           "options": [{"label": "Mare", "value": "Mare"}, {"label": "Monti", "value": "Monti"}]})
    token = _token(core)
    with patch("telegram_bot.services.chat_service.run_chat_turn") as turn:
        aq.handle_callback(_call(f"ask:{token}:1"))
    assert posted[-1][1]["answer"] == "Monti" and posted[-1][1]["question_id"] == "ask_1"
    turn.assert_called_once()
    assert turn.call_args[0][2].endswith(": Monti")
    from telegram_bot import store
    assert store.get_pending(token) is None


@pytest.mark.unit
def test_multi_choice_toggles_then_sends_lines(env):
    core, posted = env
    from telegram_bot.services import assistant_questions as aq
    aq.send(12345, "s-1", {"question_id": "ask_2", "header": "Quali?", "kind": "multi_choice",
                           "options": [{"label": "A", "value": "A"}, {"label": "B", "value": "B"}, {"label": "C", "value": "C"}]})
    token = _token(core)
    aq.handle_callback(_call(f"askt:{token}:0"))
    aq.handle_callback(_call(f"askt:{token}:2"))
    aq.handle_callback(_call(f"askt:{token}:0"))   # untick
    with patch("telegram_bot.services.chat_service.run_chat_turn"):
        aq.handle_callback(_call(f"asks:{token}"))
    assert posted[-1][1]["answer"] == "C"


@pytest.mark.unit
def test_free_text_is_the_next_message(env, fake_message):
    core, posted = env
    from telegram_bot.services import assistant_questions as aq
    from telegram_bot import store
    import telegram_runtime
    aq.send(12345, "s-1", {"question_id": "ask_3", "header": "Rispondi", "kind": "free_text", "options": []})
    assert store.get_flow(12345)["kind"] == aq.TEXT_FLOW
    with patch("telegram_bot.services.chat_service.run_chat_turn") as turn, \
            patch("telegram_bot.menu.model.current", return_value=_menu()):
        telegram_runtime.on_message(fake_message(text="Chiamalo Ciro", chat_id=12345, message_id=9))
    assert posted[-1][1]["answer"] == "Chiamalo Ciro"
    assert turn.call_args[0][2].endswith(": Chiamalo Ciro")


@pytest.mark.unit
def test_oracle_question_frames_route_ask_ids_here(env):
    core, _ = env
    from telegram_bot.services.chat_service import send_oracle_questions
    send_oracle_questions(12345, "s-1", [], [{"question_id": "ask_4", "header": "Confermi?", "kind": "confirm",
                                               "options": [{"label": "Sì", "value": "si"}, {"label": "No", "value": "no"}]}])
    from telegram_bot import store
    entry = store.get_pending(_token(core))
    assert entry["action"] == "assistant_question" and entry["kind"] == "confirm"

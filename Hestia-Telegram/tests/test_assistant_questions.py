"""Questions the assistant asks in the chat (docs/work/2026-10-19-oracle-offline v3 A)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def env(monkeypatch):
    import telegram_bot.core as core
    core.ALLOWED_USER_ID = "99999"
    core.bot = MagicMock()
    core.PENDING_CONFIRMATIONS.clear()
    core.PENDING_WORKFLOWS.clear()
    posted = []

    def post(url, json=None, **kw):
        posted.append((url, json))
        return MagicMock(status_code=200, content=b"x",
                         json=lambda: {"resolved": True, "resume": {"message": "Risposta alla tua domanda «Q»: " + json["answer"]}})

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr(core, "resolve_oracle_chat_url", lambda: "http://oracle/api/chat")
    return core, posted


def _call(data, chat_id=12345):
    return MagicMock(data=data, id="cb", message=MagicMock(chat=MagicMock(id=chat_id), message_id=50,
                                                            html_text="<b>Scegli</b>", text="Scegli"))


def _token(core):
    return next(iter(core.PENDING_CONFIRMATIONS))


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
    assert token not in core.PENDING_CONFIRMATIONS


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
    from telegram_bot.services.chat_service import handle_chat_message
    aq.send(12345, "s-1", {"question_id": "ask_3", "header": "Rispondi", "kind": "free_text", "options": []})
    assert core.PENDING_WORKFLOWS["12345"]["action"] == aq.TEXT_FLOW
    with patch("telegram_bot.services.chat_service.run_chat_turn") as turn:
        handle_chat_message(fake_message(text="Chiamalo Ciro", chat_id=12345, message_id=9))
    assert posted[-1][1]["answer"] == "Chiamalo Ciro"
    assert turn.call_args[0][2].endswith(": Chiamalo Ciro")


@pytest.mark.unit
def test_oracle_question_frames_route_ask_ids_here(env):
    core, _ = env
    from telegram_bot.services.chat_service import send_oracle_questions
    send_oracle_questions(12345, "s-1", [], [{"question_id": "ask_4", "header": "Confermi?", "kind": "confirm",
                                               "options": [{"label": "Sì", "value": "si"}, {"label": "No", "value": "no"}]}])
    entry = core.PENDING_CONFIRMATIONS[_token(core)]
    assert entry["action"] == "assistant_question" and entry["kind"] == "confirm"

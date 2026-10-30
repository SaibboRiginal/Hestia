"""Questions in notifications (docs/work/2026-10-30-domande-nelle-notifiche): same keyboard as the chat question,
answer → Hermes; free text only after «Rispondi…»/«Altro…» or as a reply to the notification."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def env(monkeypatch, _ui_store):
    import telegram_bot.core as core
    core.ALLOWED_USER_ID = "12345"
    core.bot = MagicMock()
    sent = MagicMock(message_id=77)
    monkeypatch.setattr(core, "send_user_message", MagicMock(return_value=[sent]))
    replies = []

    def hermes(path, body=None, method="POST", timeout=20):
        replies.append((path, body))
        return 200, {"status": "done"}

    from telegram_bot.services import notifications
    monkeypatch.setattr(notifications, "_hermes", hermes)
    return core, replies


def _deliver(question, **extra):
    from telegram_bot.services import notifications
    return notifications.handle_notify({"kind": "notification", "notification_id": "n1", "target": "owner",
                                        "title": "Routine", "message": "Cosa compro?", "question": question, **extra})


def _markup(core):
    return core.send_user_message.call_args.kwargs["reply_markup"]


def _token():
    from telegram_bot.services import assistant_questions
    return assistant_questions.token_for_notification("n1")


def _call(data):
    return MagicMock(data=data, id="cb", message=MagicMock(chat=MagicMock(id=12345), message_id=77,
                                                            html_text="<b>Routine</b>", text="Routine"))


@pytest.mark.unit
def test_single_choice_answers_hermes(env):
    core, replies = env
    status, _ = _deliver({"kind": "single_choice", "options": [{"value": "a", "label": "Pane"},
                                                               {"value": "b", "label": "Latte"}]})
    assert status == 200
    labels = [b.text for row in _markup(core).keyboard for b in row]
    assert labels == ["Pane", "Latte"]
    from telegram_bot.services import assistant_questions as aq
    aq.handle_callback(_call(f"ask:{_token()}:1"))
    assert replies[-1] == ("api/notifications/n1/reply", {"answer": "b", "client": "telegram"})
    assert _token() == ""


@pytest.mark.unit
def test_multi_choice_with_other_and_link(env, monkeypatch):
    core, replies = env
    from telegram_bot import webapp
    monkeypatch.setattr(webapp, "open_button", lambda label, path: MagicMock(text=label))
    _deliver({"kind": "multi_choice", "allow_other": True, "options": ["A", "B"]},
             link={"module": "chronos", "page": "routine"})
    labels = [b.text for row in _markup(core).keyboard for b in row]
    assert labels == ["A", "B", "Invia", "Altro…", "Apri"]
    assert "Oppure «Altro…»" in core.send_user_message.call_args.args[1]
    from telegram_bot.services import assistant_questions as aq
    token = _token()
    aq.handle_callback(_call(f"askt:{token}:0"))
    aq.handle_callback(_call(f"askw:{token}"))
    from telegram_bot import store
    flow = store.get_flow(12345)
    assert flow["kind"] == aq.TEXT_FLOW
    assert aq.answer_text(MagicMock(), flow, "Caffè") is True
    assert replies[-1][1]["answer"] == "A\nCaffè"
    assert store.get_flow(12345) is None


@pytest.mark.unit
def test_free_text_is_not_taken_from_any_message(env):
    """A notification arrives unasked: the next message is a normal chat turn, a reply to it is the answer."""
    core, replies = env
    _deliver({"kind": "free_text"})
    from telegram_bot import store
    from telegram_bot.services import notifications
    assert store.get_flow(12345) is None
    labels = [b.text for row in _markup(core).keyboard for b in row]
    assert labels == ["Rispondi…"]
    plain = MagicMock(reply_to_message=None, chat=MagicMock(id=12345))
    assert notifications.answer_by_reply(plain, "ciao") is False
    reply = MagicMock(reply_to_message=MagicMock(message_id=77), chat=MagicMock(id=12345))
    assert notifications.answer_by_reply(reply, "Due litri") is True
    assert replies[-1] == ("api/notifications/n1/reply", {"answer": "Due litri", "client": "telegram"})


@pytest.mark.unit
def test_already_handled_elsewhere(env, monkeypatch):
    core, _ = env
    from telegram_bot.services import notifications
    monkeypatch.setattr(notifications, "_hermes", lambda *a, **k: (409, {"status": "already_handled"}))
    _deliver({"kind": "confirm", "options": [{"value": "si", "label": "Sì"}, {"value": "no", "label": "No"}]})
    from telegram_bot.services import assistant_questions as aq
    aq.handle_callback(_call(f"ask:{_token()}:0"))
    assert "già stata gestita" in core.bot.send_message.call_args.args[1]

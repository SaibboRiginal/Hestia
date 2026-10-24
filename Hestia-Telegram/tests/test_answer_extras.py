"""Components, origin label and undo buttons under an answer (docs/work/2026-10-24-tutto-brainstorm-cindy)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def bot():
    import telegram_bot.core as core
    core.ALLOWED_USER_ID = "99999"
    core.bot = MagicMock()
    core.bot.send_message.return_value = MagicMock(message_id=500)
    return core.bot


def _renderer():
    from telegram_bot.services.reply_renderer import ReplyRenderer
    return ReplyRenderer(12345, 50, {})


@pytest.mark.unit
def test_components_become_text_and_buttons(bot):
    r = _renderer()
    r.on_final("Ecco\n```hestia-ui\n{\"c\":\"stat\",\"label\":\"Speso\",\"value\":\"12 €\"}\n"
               "{\"c\":\"button\",\"label\":\"Dettagli\",\"send\":\"mostra dettagli\"}\n```",
               {"level": "routine", "label": "Da una tua routine"})
    shown = bot.edit_message_text.call_args[0][0]
    assert "Speso: 12 €" in shown and "hestia-ui" not in shown and "Da una tua routine" in shown
    assert r.buttons[0]["send"] == "mostra dettagli"


@pytest.mark.unit
def test_owner_turn_has_no_origin_label(bot):
    r = _renderer()
    r.on_final("ciao", {"level": "utente", "label": "Tu"})
    assert r.origin_label == ""


@pytest.mark.unit
def test_changes_get_an_undo_tool_button(bot):
    from telegram_bot import actions, store
    from telegram_bot.services import answer_extras
    text, markup = answer_extras.changes_view({"items": [
        {"tool": "finance_add", "title": "Registra spesa", "detail": "12 € bar",
         "undo": {"tool": "finance_delete", "args": {"id": "t1"}, "label": "Annulla"}},
        {"tool": "note_add", "title": "Nota"}]})
    assert "Registra spesa" in text and "Nota" in text
    buttons = [b for row in markup.keyboard for b in row]
    assert len(buttons) == 1
    _, tool_id, values_id = buttons[0].callback_data.split(":")
    assert store.resolve(tool_id) == "finance_delete"
    assert actions._values_of(values_id) == {"id": "t1"}


@pytest.mark.unit
def test_nothing_to_undo_means_no_keyboard(bot):
    from telegram_bot.services import answer_extras
    _, markup = answer_extras.changes_view({"items": [{"tool": "x", "title": "X"}]})
    assert markup is None


@pytest.mark.unit
def test_component_button_sends_its_text_to_the_chat(bot):
    from telegram_bot.services import answer_extras
    answer_extras.send_buttons(12345, [{"label": "Dettagli", "send": "mostra dettagli"}])
    data = bot.send_message.call_args.kwargs["reply_markup"].keyboard[0][0].callback_data
    assert answer_extras.is_callback(data)
    call = MagicMock(data=data, id="cb", message=MagicMock(chat=MagicMock(id=12345)))
    with patch("telegram_bot.services.chat_service.chat_from_text") as chat:
        answer_extras.handle_callback(call)
    chat.assert_called_once_with(12345, "mostra dettagli")

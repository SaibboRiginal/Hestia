"""The assistant wrote first («parla con te», docs/work/2026-11-12-identita-e-proattivita): a notification whose
payload has ``_chat`` is plain chat text, not a card. Markers: unit."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_chat_message_is_plain_text_without_card_or_cut():
    from telegram_bot.services import notifications
    text = "Com'è andata poi la riunione di stamattina? Ieri mi sembravi teso, e <oggi> non ti ho più sentito."
    body = {"title": "", "message": text, "level": "info", "payload": {"kind": "athena.talk", "_chat": True}}
    html = notifications.render_notification(body)
    assert html == text.replace("<", "&lt;").replace(">", "&gt;") and "<b>" not in html


def test_other_notifications_stay_cards():
    from telegram_bot.services import notifications
    body = {"title": "Spesa", "message": "12 € al bar", "level": "info", "payload": {"kind": "plutus.expense"}}
    assert notifications.is_chat_message(body) is False
    assert "<b>" in notifications.render_notification(body)

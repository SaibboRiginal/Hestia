"""Emoji reactions both ways (docs/work/2026-11-06-hestia-viva F4). Markers: unit."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def bot(monkeypatch):
    import telegram_bot.core as core_module
    core_module.ALLOWED_USER_ID = "99999"
    fake = MagicMock()
    core_module.bot = fake
    monkeypatch.setattr(core_module, "get_session", lambda chat: "s-1")
    return fake


def test_telegram_emoji_maps_or_skips():
    from telegram_bot.services import reactions
    assert reactions.telegram_emoji("👍") == "👍"
    assert reactions.telegram_emoji("❤️") == "❤"          # variation selector dropped
    assert reactions.telegram_emoji("😂") == "🤣"
    assert reactions.telegram_emoji("🦖") == ""


def test_react_sets_reaction_on_the_owner_message(bot):
    from telegram_bot.services import reactions
    assert reactions.react(5, 77, "😂") is True
    chat, mid, kinds = bot.set_message_reaction.call_args[0]
    assert (chat, mid) == (5, 77) and kinds[0].emoji == "🤣"
    bot.set_message_reaction.reset_mock()
    assert reactions.react(5, 77, "🦖") is False and not bot.set_message_reaction.called


def test_stream_reaction_only_deletes_the_status_message(bot):
    from telegram_bot.services.chat_service import consume_oracle_stream
    renderer = MagicMock(chat_id=5, msg_id=40, reaction="")
    lines = [json.dumps({"type": "reaction", "emoji": "👍"}).encode(),
             json.dumps({"type": "final", "reply": "", "reaction": "👍", "reaction_only": True}).encode()]
    consume_oracle_stream(SimpleNamespace(iter_lines=lambda: iter(lines)), renderer, [], [])
    assert renderer.reaction == "👍" and renderer.finalized is True
    renderer.on_final.assert_not_called()
    bot.delete_message.assert_called_once_with(5, 40)


def test_owner_reaction_goes_to_oracle(bot, monkeypatch):
    from telegram_bot import catalog
    from telegram_bot.services import reactions, voice_service
    voice_service.remember_answer(5, 81, "Domani piove.")
    sent = []
    monkeypatch.setattr(catalog, "route", lambda *a, **k: sent.append((a, k)) or (True, {"ok": True}))
    update = SimpleNamespace(user=SimpleNamespace(id=99999), chat=SimpleNamespace(id=5), message_id=81,
                             new_reaction=[SimpleNamespace(type="emoji", emoji="❤")])
    reactions.on_owner_reaction(update)
    (service, path, method), kw = sent[0]
    assert (service, path, method) == ("oracle", "api/chat/reaction", "POST")
    assert kw["body"] == {"session_id": "s-1", "emoji": "❤", "text": "Domani piove."}
    sent.clear()
    reactions.on_owner_reaction(SimpleNamespace(user=SimpleNamespace(id=1), chat=SimpleNamespace(id=5),
                                                message_id=81, new_reaction=[]))
    assert sent == []                                       # not the owner

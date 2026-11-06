"""Setup mode: the one-time code links the owner (docs/work/2026-10-30-setup-un-click §4.2)."""
from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest

from telegram_bot import core
from telegram_bot.services import setup_link


def _msg(text, user=777):
    return NS(text=text, from_user=NS(id=user), chat=NS(id=user))


def _hub(payload):
    resp = MagicMock()
    resp.json.return_value = {"status_code": 200, "payload": payload}
    return resp


@pytest.mark.unit
def test_owner_configured_ignores_codes(monkeypatch):
    monkeypatch.setattr(core, "ALLOWED_USER_ID", "99999")
    with patch("telegram_bot.services.setup_link.requests.post") as post:
        assert setup_link.try_claim(_msg("123456")) is False
    post.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("text", ["ciao", "12345", "1234567", "codice 123456"])
def test_only_six_digits_count(monkeypatch, text):
    monkeypatch.setattr(core, "ALLOWED_USER_ID", "")
    with patch("telegram_bot.services.setup_link.requests.post") as post:
        assert setup_link.try_claim(_msg(text)) is False
    post.assert_not_called()


@pytest.mark.unit
def test_right_code_links_sender(monkeypatch):
    monkeypatch.setattr(core, "ALLOWED_USER_ID", "")
    bot = MagicMock()
    monkeypatch.setattr(core, "bot", bot)
    with patch("telegram_bot.services.setup_link.requests.post", return_value=_hub({"ok": True})) as post:
        assert setup_link.try_claim(_msg(" 042317 ", user=555)) is True
    assert post.call_args.args[0].endswith("/route/hephaestus/api/setup/telegram/claim")
    assert post.call_args.kwargs["json"]["body"] == {"code": "042317", "user_id": "555"}
    assert "ti riconosco" in bot.reply_to.call_args.args[1]


@pytest.mark.unit
def test_wrong_code_says_so(monkeypatch):
    monkeypatch.setattr(core, "ALLOWED_USER_ID", "")
    bot = MagicMock()
    monkeypatch.setattr(core, "bot", bot)
    with patch("telegram_bot.services.setup_link.requests.post",
               return_value=_hub({"ok": False, "reason": "wrong_code"})):
        assert setup_link.try_claim(_msg("111111")) is True
    assert "non è giusto" in bot.reply_to.call_args.args[1]

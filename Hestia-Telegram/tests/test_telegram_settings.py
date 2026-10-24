"""Tests — Telegram settings declared to Themis (central settings, P6)."""
from __future__ import annotations

import pytest

import telegram_settings as ts


@pytest.fixture(autouse=True)
def _defaults():
    ts.settings.apply({})          # every key back to its default
    yield
    ts.settings.apply({})


@pytest.mark.unit
class TestDeclaredSettings:
    def test_keys_declared_with_former_env_defaults(self):
        defs = ts.settings._defs
        expected = {
            "telegram.feedback.prompt_rate": 0.15,              # TELEGRAM_FEEDBACK_PROMPT_RATE
            "telegram.feedback.snooze_days": 7,                 # FEEDBACK_SNOOZE_DEFAULT_DAYS
            "telegram.chat.locale": "it",                       # TELEGRAM_LOCALE
            "telegram.chat.client_instructions": ts.DEFAULT_CLIENT_INSTRUCTIONS,
            "telegram.oracle.stream_timeout": 600,              # TELEGRAM_ORACLE_STREAM_TIMEOUT
            "telegram.menu.layout": {},                         # menus as configuration (telegram-da-zero §5.11)
        }
        for key, default in expected.items():
            assert key in defs, key
            assert defs[key]["default"] == default, key
            assert defs[key]["apply"] == "live", key
            assert defs[key]["scope"] == "system", key
        assert "telegram.log.level" in defs
        assert all(k.startswith("telegram.") for k in defs)

    def test_removed_keys_are_gone(self):
        defs = ts.settings._defs
        for key in ("telegram.alerts.buffer_window", "telegram.commands.hidden", "telegram.commands.hidden_services",
                    "telegram.signals.style", "telegram.signals.style_memory", "telegram.signals.style_action"):
            assert key not in defs, key

    def test_client_instructions_ask_for_no_emoji(self):
        assert "NIENTE EMOJI" in ts.DEFAULT_CLIENT_INSTRUCTIONS

    def test_personal_chat_settings_stay_separate(self):
        from telegram_bot.services import personal_settings
        assert not any(k in ts.settings._defs for k in personal_settings.KEYS.values())


@pytest.mark.unit
class TestLiveValues:
    def test_locale_and_instructions_follow_setting(self):
        from telegram_bot import core
        assert core.locale() == "it"
        assert core.client_instructions() == ts.DEFAULT_CLIENT_INSTRUCTIONS
        ts.settings.apply({"telegram.chat.locale": "en", "telegram.chat.client_instructions": "breve"})
        assert core.locale() == "en"
        assert core.client_instructions() == "breve"

    def test_reload_payload_applies_values(self):
        out = ts.reload_payload({"values": {"telegram.feedback.snooze_days": 3}})
        assert out["owner"] == "telegram"
        assert "telegram.feedback.snooze_days" in out["applied"]
        assert ts.settings.get(ts.FEEDBACK_SNOOZE_DAYS) == 3
        assert ts.effective_payload()["values"]["telegram.feedback.snooze_days"] == 3

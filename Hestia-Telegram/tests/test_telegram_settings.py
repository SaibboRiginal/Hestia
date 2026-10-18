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
            "telegram.alerts.buffer_window": 0.8,               # ALERT_BUFFER_WINDOW_SECONDS
            "telegram.feedback.prompt_rate": 0.15,              # TELEGRAM_FEEDBACK_PROMPT_RATE
            "telegram.feedback.snooze_days": 7,                 # FEEDBACK_SNOOZE_DEFAULT_DAYS
            "telegram.commands.hidden_services": [],            # TELEGRAM_HIDDEN_COMMAND_SERVICES
            "telegram.commands.hidden": ["notifica_attiva", "notifica_disattiva", "notifiche_attive"],
            "telegram.chat.locale": "it",                       # TELEGRAM_LOCALE
            "telegram.chat.client_instructions": ts.DEFAULT_CLIENT_INSTRUCTIONS,
            "telegram.oracle.stream_timeout": 600,              # TELEGRAM_ORACLE_STREAM_TIMEOUT
            "telegram.signals.style": "minimal",                # TELEGRAM_SIGNAL_STYLE
            "telegram.signals.style_memory": "",                # TELEGRAM_SIGNAL_STYLE_BY_FAMILY
            "telegram.signals.style_subscription": "",
            "telegram.signals.style_action": "compact",
            "telegram.signals.style_other": "",
        }
        for key, default in expected.items():
            assert key in defs, key
            assert defs[key]["default"] == default, key
            assert defs[key]["apply"] == "live", key
            assert defs[key]["scope"] == "system", key
        assert "telegram.log.level" in defs
        assert all(k.startswith("telegram.") for k in defs)

    def test_signal_style_enum_options(self):
        values = [o["value"] for o in ts.settings._defs["telegram.signals.style"]["options"]]
        assert values == ["minimal", "compact", "rich"]
        family = [o["value"] for o in ts.settings._defs["telegram.signals.style_memory"]["options"]]
        assert family == ["", "minimal", "compact", "rich"]

    def test_personal_chat_settings_stay_separate(self):
        from telegram_bot.services import personal_settings
        assert not any(k in ts.settings._defs for k in personal_settings.KEYS.values())


@pytest.mark.unit
class TestLiveValues:
    def test_hidden_commands_follow_setting(self):
        from telegram_bot import core
        assert core.hidden_command_services() == set()
        ts.settings.apply({"telegram.commands.hidden_services": ["Scout", " "],
                           "telegram.commands.hidden": ["x"]})
        assert core.hidden_command_services() == {"scout"}
        assert core.hidden_dynamic_commands() == {"x"}

    def test_locale_and_instructions_follow_setting(self):
        from telegram_bot import core
        assert core.locale() == "it"
        assert core.client_instructions() == ts.DEFAULT_CLIENT_INSTRUCTIONS
        ts.settings.apply({"telegram.chat.locale": "en", "telegram.chat.client_instructions": "breve"})
        assert core.locale() == "en"
        assert core.client_instructions() == "breve"

    def test_signal_style_base_family_and_forced(self):
        import message_format as mf
        assert mf._resolve_signal_style({}, "memory.saved") == "minimal"
        ts.settings.apply({"telegram.signals.style": "rich"})
        assert mf._resolve_signal_style({}, "memory.saved") == "rich"
        ts.settings.apply({"telegram.signals.style": "rich", "telegram.signals.style_memory": "compact"})
        assert mf._resolve_signal_style({}, "memory.saved") == "compact"
        assert mf._resolve_signal_style({}, "action.done") == "compact"   # default family override
        assert mf._resolve_signal_style({}, "other.thing") == "rich"
        forced = {"ui": {"telegram": {"style": "minimal"}}}
        assert mf._resolve_signal_style(forced, "memory.saved") == "minimal"

    def test_reload_payload_applies_values(self):
        out = ts.reload_payload({"values": {"telegram.feedback.snooze_days": 3}})
        assert out["owner"] == "telegram"
        assert "telegram.feedback.snooze_days" in out["applied"]
        assert ts.settings.get(ts.FEEDBACK_SNOOZE_DAYS) == 3
        assert ts.effective_payload()["values"]["telegram.feedback.snooze_days"] == 3

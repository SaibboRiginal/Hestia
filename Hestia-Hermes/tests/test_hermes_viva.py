"""Notification style «Frase di Hestia» (docs/work/2026-11-06-hestia-viva F5). Markers: unit."""
from __future__ import annotations

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def _say(message, style="frase", level="info", event_type="note.saved", payload=None):
    from modules.service import conversational_message
    return conversational_message(message, "Titolo", level=level, event_type=event_type, payload=payload or {},
                                  style=style)


def test_card_style_is_unchanged_and_skips_oracle():
    with patch("modules.service.narrate") as narrate:
        assert _say("Spesa salvata", style="scheda") == "Spesa salvata"
        narrate.assert_not_called()


def test_phrase_style_narrates_an_informative_notification():
    with patch("modules.service.narrate", return_value=" Ho segnato la spesa di 12 €. ") as narrate:
        assert _say("Spesa salvata: 12 €") == "Ho segnato la spesa di 12 €."
        assert "Spesa salvata: 12 €" in narrate.call_args[0][0]


@pytest.mark.parametrize("kw", [{"level": "warning"}, {"level": "error"}, {"event_type": "service.health"},
                                {"payload": {"_actions": [{"label": "Ok"}]}}, {"payload": {"_question": {"k": 1}}},
                                {"payload": {"_secret": True}}])
def test_alerts_buttons_questions_stay_cards(kw):
    with patch("modules.service.narrate") as narrate:
        assert _say("Testo", **kw) == "Testo"
        narrate.assert_not_called()


def test_oracle_down_keeps_the_card_text():
    with patch("modules.service.narrate", return_value=""):
        assert _say("Testo originale") == "Testo originale"


def test_style_setting_is_declared_with_card_default():
    from modules import hermes_settings
    assert hermes_settings.NOTIFICATION_STYLE == "hermes.notifiche.stile"
    assert [v for v, _ in hermes_settings.STYLES] == ["scheda", "frase"]

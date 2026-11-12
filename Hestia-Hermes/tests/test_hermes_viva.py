"""Notification style «Frase di Hestia» (docs/work/2026-11-06-hestia-viva F5). Markers: unit."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def test_phrase_style_leaves_the_identity_to_oracle():
    """Hermes sends what to say and the data; who speaks (name, she/he, owner) is Oracle's system prompt, asked
    with ``voice`` (docs/work/2026-11-12-prompt-ogni-situazione): no «Sei …» written here."""
    with patch("modules.service.narrate", return_value="Fatto.") as narrate:
        _say("Spesa salvata")
    prompt = narrate.call_args[0][0]
    assert prompt.startswith("Say this notification in ONE short natural sentence") and "Sei " not in prompt
    assert "Text: Spesa salvata" in prompt


def test_narrate_asks_oracle_for_the_assistant_voice():
    from modules import oracle_client
    resp = MagicMock(status_code=200, content=b"x")
    resp.json.return_value = {"status_code": 200, "payload": {"response": "Fatto."}}
    with patch("modules.oracle_client.requests.post", return_value=resp) as post:
        oracle_client.narrate("x")
    assert post.call_args.kwargs["json"]["body"] == {"prompt": "x", "voice": True}


def test_view_exposes_the_kind_of_the_sender():
    from modules.notifications import view
    row = {"outbound_event_id": "n1", "lifecycle_state": "delivered",
           "payload": {"event_payload": {"kind": "athena.talk"}, "notification": {"message": "Ciao"}}}
    assert view(row)["kind"] == "athena.talk" and view({"payload": {}})["kind"] == ""

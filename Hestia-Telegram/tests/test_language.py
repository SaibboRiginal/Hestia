"""Fixed texts follow the owner's language setting (dossier docs/work/2026-11-14-backend-inglese)."""
from __future__ import annotations

import pytest

from hestia_common import i18n


@pytest.fixture
def english():
    i18n.use(lambda key: "en" if key == "themis.personal.language" else None)
    yield
    i18n.use(None)


@pytest.mark.unit
def test_italian_by_default():
    from telegram_bot import ui
    assert ui.button(ui.CANCEL, "x").text == "Annulla"
    assert i18n.t("Oggi — {0}", "lunedì") == "Oggi — lunedì"


@pytest.mark.unit
def test_buttons_cards_and_notes_follow_english(english):
    from telegram_bot import ui
    assert ui.button(ui.CANCEL, "x").text == "Cancel"
    assert ui.card("Tutte le azioni", [ui.note("Niente di nuovo.")]) == "<b>All actions</b>\n<i>Nothing new.</i>"
    assert i18n.t("Oggi — {0}", "monday") == "Today — monday"


@pytest.mark.unit
def test_bottom_keyboard_matches_both_languages(english):
    from telegram_bot.menu import model as menu_model
    menu = menu_model.Menu.__new__(menu_model.Menu)
    menu.doors = {"oggi": "Oggi"}
    assert menu.door_for_text("Today") == "oggi" and menu.door_for_text("oggi") == "oggi"


@pytest.mark.unit
def test_every_english_text_keeps_its_placeholders():
    import re
    for source, text in i18n.catalog("messages", "en").items():
        if source.startswith("• {0} notific"):
            continue
        fields = r"\{\d+[^{}]*\}|\{[a-z_]+\}"     # str.format fields, not JSON examples in help texts
        assert sorted(re.findall(fields, source)) == sorted(re.findall(fields, text)), source

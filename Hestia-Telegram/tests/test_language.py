"""Fixed texts follow the owner's language setting (dossier docs/work/2026-11-14-backend-inglese)."""
from __future__ import annotations

import re

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


@pytest.mark.unit
def test_english_tools_catalog_covers_every_italian_tool():
    from hestia_common import i18n
    it, en = i18n.catalog("tools", "it"), i18n.catalog("tools", "en")
    for name, entry in it.items():
        if name == "_about":
            continue
        assert name in en, name
        assert bool(en[name].get("summary")) == bool(entry.get("summary")), name
        assert set(en[name].get("params") or {}) == set(entry.get("params") or {}), name
    assert i18n.tool_summary("agenda", "en").startswith("Shows")
    assert i18n.tool_summary("agenda", "de").startswith("Shows")  # a language without a catalog → English


def _check_i18n():
    """The governance gate tools/governance/check_i18n.py (the standard: docs/LANGUAGES.md)."""
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "tools" / "governance" / "check_i18n.py"
    spec = importlib.util.spec_from_file_location("check_i18n", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.unit
def test_every_module_text_has_an_english_translation():
    """Every ``tr("…")`` literal in the Python modules is in the English catalog."""
    gate = _check_i18n()
    en = i18n.catalog("messages", "en")
    missing = [f"{p.name}: {t[:60]}" for p, t in gate.python_texts() if t not in en]
    assert not missing, missing[:20]


@pytest.mark.unit
def test_every_webui_and_plugin_text_has_an_english_translation():
    """Every ``tr('…')`` / ``'…' | tr`` literal of the WebUI shell, the plugins and the SDK kit is in the English catalog."""
    gate = _check_i18n()
    en = i18n.catalog("messages", "en")
    texts = list(gate.web_texts())
    assert len(texts) > 1000, len(texts)
    missing = [f"{p.name}: {t[:60]}" for p, t in texts if t not in en]
    assert not missing, missing[:20]

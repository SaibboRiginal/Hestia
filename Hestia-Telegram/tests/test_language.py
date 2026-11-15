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
    assert i18n.tool_summary("agenda", "de").startswith("Shows")  # no German catalog yet → English


_IT = re.compile(r"[àèéìòù]|\b(il|la|le|non|per|che|della|del|una|sono|nessun[ao]?|serve|riprova|trovat[oa])\b", re.I)


@pytest.mark.unit
def test_every_module_text_has_an_english_translation():
    """Every ``tr("…")`` literal in the modules (Telegram excluded: its own test above) is in the English catalog."""
    import ast
    from pathlib import Path
    from hestia_common import i18n
    en = i18n.catalog("messages", "en")
    root = Path(__file__).resolve().parents[2]
    missing = []
    for path in root.glob("Hestia-*/**/*.py"):
        if "/tests/" in str(path) or "Hestia-Telegram" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "tr" and n.args
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
                text = n.args[0].value
                if text not in en and _IT.search(text):
                    missing.append(f"{path.relative_to(root)}: {text[:60]}")
    assert not missing, missing[:20]


# A quoted literal; `\\'` is an Angular template quote escaped inside a TS string.
_Q = r"""'(?:\\\\.|[^'\\\n]|\\.)*'""" + r'''|"(?:\\\\.|[^"\\\n]|\\.)*"'''
_TS_TR = re.compile(rf"""\btr\(\s*({_Q})\s*[,)]|({_Q})\s*\|\s*tr\b""")


def _ts_unquote(lit: str) -> str:
    body = re.sub(r"\\\\(['\"])", r"\1", lit[1:-1])
    return re.sub(r"\\(u\{?[0-9a-fA-F]+\}?|.)", lambda m: {
        "n": "\n", "t": "\t", "\\": "\\", "'": "'", '"': '"', "`": "`", "$": "$",
    }.get(m.group(1), None) or (chr(int(m.group(1)[1:].strip("{}"), 16)) if m.group(1)[0] == "u" else m.group(1)), body)


@pytest.mark.unit
def test_every_webui_and_plugin_text_has_an_english_translation():
    """Every ``tr('…')`` / ``'…' | tr`` literal of the WebUI shell, the plugins and the SDK kit is in the English catalog."""
    from pathlib import Path
    from hestia_common import i18n
    en = i18n.catalog("messages", "en")
    root = Path(__file__).resolve().parents[2]
    files = [*root.glob("Hestia-WebUI/frontend/src/**/*.ts"), *root.glob("Hestia-WebUI/frontend/src/**/*.html"),
             *root.glob("Hestia-*/ui/src/**/*.ts"), *root.glob("Hestia-Shared/webui-sdk/src/**/*.ts")]
    missing, seen = [], 0
    for path in files:
        if "node_modules" in path.parts or path.name == "i18n.ts":
            continue
        for m in _TS_TR.finditer(path.read_text(encoding="utf-8")):
            text = _ts_unquote(m.group(1) or m.group(2))
            seen += 1
            if text and text not in en:
                missing.append(f"{path.relative_to(root)}: {text[:60]}")
    assert seen > 1000, seen
    assert not missing, missing[:20]

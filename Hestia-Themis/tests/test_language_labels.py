"""Settings are served in the owner's language (dossier docs/work/2026-11-14-backend-inglese, phase 2b)."""
from __future__ import annotations

import pytest

from hestia_common.settings_client import PERSONAL, setting, translated


@pytest.mark.unit
def test_translated_changes_texts_not_keys_or_values():
    d = setting("x.tone", "Tono del recap", "enum", "amichevole", group="Personali",
                options=[("amichevole", "Sempre"), ("asciutto", "Solo errori")], help="Lunghezza massima del recap")
    en = translated(d, "en")
    assert en["label"] == "Recap tone" and en["group"] == "Personal"
    assert [o["value"] for o in en["options"]] == ["amichevole", "asciutto"]
    assert [o["label"] for o in en["options"]] == ["Always", "Errors only"]
    assert en["key"] == "x.tone" and en["default"] == "amichevole"
    assert translated(d, "it") is d


@pytest.mark.unit
def test_every_personal_setting_has_an_english_label():
    for d in PERSONAL.values():
        assert translated(d, "en")["label"] != d["label"] or d["label"] in ("Account",), d["key"]

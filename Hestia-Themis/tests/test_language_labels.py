"""Settings are served in the owner's language (dossier docs/work/2026-11-14-english-backend, phase 2b).

Definitions are written in English (the source); ``translated`` gives the Italian at the edge."""
from __future__ import annotations

import pytest

from hestia_common.settings_client import PERSONAL, setting, translated


@pytest.mark.unit
def test_translated_changes_texts_not_keys_or_values():
    d = setting("x.tone", "Recap tone", "enum", "amichevole", group="Personal",
                options=[("amichevole", "Always"), ("asciutto", "Errors only")])
    it = translated(d, "it")
    assert it["label"] == "Tono del recap" and it["group"] == "Personali"
    assert [o["value"] for o in it["options"]] == ["amichevole", "asciutto"]
    assert [o["label"] for o in it["options"]] == ["Sempre", "Solo errori"]
    assert it["key"] == "x.tone" and it["default"] == "amichevole"
    assert translated(d, "en")["label"] == "Recap tone"


@pytest.mark.unit
def test_every_personal_setting_has_an_italian_label():
    for d in PERSONAL.values():
        assert translated(d, "it")["label"] != d["label"] or d["label"] in ("Account",), d["key"]

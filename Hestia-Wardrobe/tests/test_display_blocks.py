"""Wardrobe cards for Telegram (docs/work/2026-10-23-telegram-da-zero §6)."""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import main  # noqa: E402


@pytest.mark.unit
def test_suggest_card_one_button_per_idea():
    d = main.suggest_display({"hint": "fresco", "weather": {"temp_c": 14.2, "rain": False}, "items": [
        {"name": "Ufficio blu", "saved": True, "pieces": ["Camicia (sopra)"], "piece_ids": ["p1"], "why": ["giusta stagione"]},
        {"name": "", "saved": False, "pieces": ["Felpa (sopra)", "Jeans (sotto)"], "piece_ids": ["p2", "p3"], "why": []}]})
    assert d["subtitle"] == "fresco · 14°"
    assert d["items"][1] == {"title": "Idea 2", "meta": ["Felpa (sopra), Jeans (sotto)"]}
    assert d["actions"][0] == {"label": "Metto Ufficio blu", "tool": "wardrobe_log_worn", "args": {"outfit": "Ufficio blu"},
                               "style": "primary"}
    assert d["actions"][1]["args"] == {"pieces": ["p2", "p3"]} and d["actions"][-1]["tool"] == "wardrobe_suggest"


@pytest.mark.unit
def test_summary_card():
    d = main.summary_display({"text": "40 capi, 5 scarpe · in lavanderia 2", "laundry": ["Jeans", "Felpa"], "forgotten": []})
    assert d["lines"] == ["40 capi, 5 scarpe", "In lavanderia: Jeans, Felpa"]

"""Spending cards for Telegram (docs/work/2026-10-23-telegram-da-zero §6)."""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
for _p in (str(_ROOT), str(_ROOT.parent / "Hestia-Shared")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import main  # noqa: E402


@pytest.mark.unit
def test_summary_card_budget_and_categories():
    d = main.summary_display({"label": "ottobre 2026", "spent": 812.4, "budget": 1000, "left": 187.6, "income": 0,
                              "pace": 1200, "to_review": 2,
                              "categories": [{"label": "Spesa", "spent": 320, "budget": 300, "pct": 107}]})
    assert d["title"] == "Spese · ottobre 2026"
    assert d["lines"][0] == "Speso 812,40 € su 1.000,00 € · restano 187,60 €"
    assert d["lines"][1] == "A questo ritmo arrivi a 1.200,00 €"
    assert d["items"][0]["tone"] == "danger"
    assert d["actions"][-1] == {"label": "Da rivedere (2)", "tool": "finance_search", "args": {"to_review": True}}


@pytest.mark.unit
def test_added_card_offers_undo_as_danger():
    d = main.added_display({"id": "t1", "amount": -12.5, "merchant": "Bar", "category_label": "Bar", "date": "2026-10-24"})
    assert d["items"][0] == {"title": "Bar", "meta": ["12,50 €", "Bar", "24/10"]}
    assert d["actions"][1]["style"] == "danger" and d["actions"][1]["args"] == {"id": "t1"}


@pytest.mark.unit
def test_search_card_empty():
    assert main.search_display([], 0)["lines"] == ["Nessun movimento trovato."]

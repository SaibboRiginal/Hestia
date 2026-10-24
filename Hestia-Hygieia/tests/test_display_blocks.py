"""Self care cards for Telegram (docs/work/2026-10-23-telegram-da-zero §6)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from app import main  # noqa: E402


@pytest.mark.unit
def test_today_card_marks_due_and_offers_done():
    d = main.today_display({"routines": [
        {"name": "Sera", "state": "due", "hint": "oggi", "reason": "", "steps": [{"label": "Detergente", "include": True},
                                                                              {"label": "Retinolo", "include": False}]},
        {"name": "Maschera", "state": "off", "steps": []}]})
    assert d["items"] == [{"title": "Sera", "meta": ["da fare", "oggi", "Detergente"], "tone": "warning"}]
    assert d["actions"][0] == {"label": "Fatta: Sera", "tool": "selfcare_log", "args": {"routine": "Sera", "status": "done"},
                               "style": "primary"}


@pytest.mark.unit
def test_overview_card_alerts_and_routines():
    d = main.overview_display({"text": "2 routine", "alerts": ["Siero scade tra 5 giorni"], "in_use": ["Siero"],
                               "routines": [{"name": "Mattina", "slot": "mattina", "cadence": "ogni giorno", "status": "active"}]})
    assert d["tone"] == "warning" and d["lines"][0] == "Siero scade tra 5 giorni"
    assert d["items"][0] == {"title": "Mattina", "meta": ["mattina", "ogni giorno"]}

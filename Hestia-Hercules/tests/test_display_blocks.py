"""Display blocks for Telegram (docs/work/2026-10-23-telegram-da-zero §6): plain Italian, existing tools."""
import pytest

from app import main


@pytest.mark.unit
def test_next_display_lists_exercises_and_starts_the_template():
    d = main._next_display({"template": {"id": "t1", "name": "Push A"}, "reason": "In programma oggi.",
                            "estimated_minutes": 55,
                            "plan": [{"exercise": "Panca piana", "sets": 4, "target": [(62.5, 8), (62.5, 8)]}]})
    assert d["title"] == "Push A" and d["subtitle"] == "In programma oggi. · 55 min"
    assert d["items"][0] == {"title": "Panca piana", "meta": ["4 serie", "62,5 kg · 8 rip"]}
    assert d["actions"][0] == {"label": "Inizia", "tool": "fitness_start_session", "args": {"template": "Push A"},
                               "style": "primary"}


@pytest.mark.unit
def test_next_display_without_template():
    d = main._next_display({"template": None, "reason": "Oggi saltato."})
    assert d["lines"] == ["Oggi saltato."] and d["actions"][0]["tool"] == "fitness_templates"


@pytest.mark.unit
def test_summary_display_active_session_offers_logging():
    d = main._summary_display({"lines": ["In corso: Push A", "PR: panca"], "flags": ["deload_suggested"],
                               "active_session": {"id": "s", "name": "Push A"}})
    assert d["subtitle"] == "In corso: Push A" and d["lines"] == ["PR: panca"] and d["tone"] == "warning"
    assert d["actions"][0]["tool"] == "fitness_log_sets"

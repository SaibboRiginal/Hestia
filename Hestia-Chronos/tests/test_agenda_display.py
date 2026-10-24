"""Agenda card for Telegram (docs/work/2026-10-23-telegram-da-zero §6)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import app.main as chronos_main

START = datetime(2026, 10, 24, tzinfo=ZoneInfo("Europe/Rome"))


@pytest.mark.unit
def test_today_lists_time_title_place():
    d = chronos_main.agenda_display([{"title": "Dentista", "start_at": "2026-10-24T16:30:00+00:00", "location": "Via Roma"},
                                     {"title": "Compleanno", "start_at": "2026-10-24T00:00:00+02:00", "all_day": True}],
                                    1, START)
    assert d["title"] == "Agenda di oggi"
    assert d["items"][0] == {"title": "Dentista", "meta": ["18:30", "Via Roma"]}
    assert d["items"][1]["meta"] == ["tutto il giorno"]
    assert [a["tool"] for a in d["actions"]] == ["create_event", "agenda"]


@pytest.mark.unit
def test_week_groups_by_day_and_empty_says_so():
    d = chronos_main.agenda_display([{"title": "Palestra", "start_at": "2026-10-26T18:00:00+01:00"}], 7, START)
    assert d["items"][0] == {"title": "Lun 26 ott", "meta": ["18:00", "Palestra"]}
    assert chronos_main.agenda_display([], 1, START)["lines"] == ["Niente in agenda."]


@pytest.mark.unit
def test_agenda_today_tool_points_to_the_one_day_route():
    paths = {getattr(r, "path", "") for r in chronos_main.app.routes}
    assert "/api/calendar/agenda/today" in paths

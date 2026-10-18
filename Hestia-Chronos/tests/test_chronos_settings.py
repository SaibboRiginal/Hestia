"""Chronos tunables are Themis settings (central settings P6), read live; no env vars."""
from __future__ import annotations

import pytest

EXPECTED = {
    "chronos.agenda.tick_seconds": 60,
    "chronos.agenda.max_attempts": 5,
    "chronos.sync.calendar_id": "primary",
    "chronos.sync.look_back_days": 1,
    "chronos.sync.look_ahead_days": 30,
    "chronos.sync.notify_new": True,
    "chronos.reminders.poll_seconds": 300,
    "chronos.reminders.look_ahead_hours": 26,
}


@pytest.mark.unit
def test_keys_declared_with_env_defaults():
    from core import chronos_settings as CS, presence_settings as PS

    assert CS.settings is PS.settings and CS.settings.owner == "chronos"   # one owner per module
    for key, default in EXPECTED.items():
        d = CS.settings._defs[key]
        assert d["default"] == default, key
        assert d["apply"] == "live" and d["label"] and d["help"], key


@pytest.mark.unit
def test_values_read_live(monkeypatch):
    from core import chronos_settings as CS
    from services import agenda, notification_worker as NW

    assert agenda._tick_seconds() == 60 and agenda._max_attempts() == 5
    assert NW._determine_bucket(25 * 60) == "1d" and NW._determine_bucket(30 * 60) is None
    monkeypatch.setitem(CS.settings._effective, CS.AGENDA_TICK, 5)            # clamped to 15
    monkeypatch.setitem(CS.settings._effective, CS.REMINDERS_LOOK_AHEAD_HOURS, 48)
    assert agenda._tick_seconds() == 15
    assert NW._determine_bucket(30 * 60) == "1d"


@pytest.mark.unit
def test_sync_interval_follows_agenda_job():
    from services import sync_worker as SW

    assert SW._interval_seconds(None) == 900
    assert SW._interval_seconds({"recurrence": "FREQ=MINUTELY;INTERVAL=30"}) == 1800
    assert SW._interval_seconds({"recurrence": "FREQ=HOURLY"}) == 3600
    assert SW._user_stopped({"status": "paused"}) and not SW._user_stopped({"status": "active"})
    assert SW._agenda_driving({"status": "paused"}) is True


@pytest.mark.unit
def test_no_tunable_env_read():
    import pathlib

    app = pathlib.Path(__file__).resolve().parents[1] / "app"
    src = "".join(p.read_text(encoding="utf-8") for p in app.rglob("*.py"))
    for name in ("CHRONOS_AGENDA_", "CHRONOS_DISPLAY_TZ", "CHRONOS_NOTIFY_", "CHRONOS_SYNC_",
                 "NOTIFY_LOOK_AHEAD_HOURS"):
        assert name not in src, name

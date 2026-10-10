"""Presence engine — signals → states → effects (SPEC docs/work/2026-10-10-assistant-presence).

No network: store, agenda window and Hermes are fakes.
"""
from __future__ import annotations

from datetime import timedelta

import pytest


@pytest.fixture
def engine():
    from services import presence as P

    calls: dict[str, list] = {"emit": [], "release": []}
    window = {"open": False}

    def store(method, path, body=None, query=None, timeout=8):
        if method == "GET" and path == "api/presence-store":
            return {"signals": [], "snapshot": None}
        return {}

    eng = P.PresenceEngine(window_status=lambda key: {"active": window["open"]}, store=store,
                           emit=lambda event, payload: calls["emit"].append(payload["base"]))
    eng._release_held = lambda level: calls["release"].append(level)
    eng._async = lambda fn, *args: fn(*args)        # synchronous for tests
    eng.load()
    eng.window, eng.calls = window, calls
    return eng


def _idle(eng, minutes):
    from services import presence as P

    eng._signals["user.last_interaction"]["value"] = P._iso(P._now() - timedelta(minutes=minutes))
    eng._windows.clear()


@pytest.mark.unit
class TestPresence:
    def test_interaction_makes_awake_and_defers_background(self, engine):
        state = engine.ping("telegram", "chat")
        assert state["base"] == "awake"
        assert state["effects"]["work.heavy"] == "defer"
        assert state["last_interaction_client"] == "telegram"

    def test_idle_nap_deep_sleep_by_inactivity(self, engine):
        engine.ping("telegram")
        _idle(engine, 10)
        assert engine.view()["base"] == "idle"
        _idle(engine, 50)
        assert engine.view()["effects"]["work.heavy"] == "local"
        _idle(engine, 200)
        assert engine.view()["base"] == "deep_sleep"

    def test_night_window_gives_deep_sleep_but_chat_wakes_up(self, engine):
        engine.ping("webui", "ui")
        _idle(engine, 10)
        engine.window["open"] = True
        assert engine.view()["base"] == "deep_sleep"
        assert engine.ping("telegram")["base"] == "awake"

    def test_hybrid_overlay_busy_with_notice(self, engine):
        engine.ping("telegram")
        engine.activity_start("forge.task", label="Forge", load="heavy", resource="claude_quota")
        state = engine.view()
        assert state["label"] == "Sveglio · Occupato: Forge"
        assert "Forge" in state["effects"]["chat.notice"]
        engine.activity_stop("forge.task")
        assert engine.view()["overlays"] == []

    def test_overlay_is_most_restrictive(self, engine):
        engine.window["open"] = True
        engine.ping("telegram")
        _idle(engine, 300)
        engine.set_signal("resource.claude_quota_left", 5)
        state = engine.view()
        assert state["base"] == "deep_sleep" and state["effects"]["llm.claude"] == "save"
        assert state["effects"]["chat.style"] == "brief"

    def test_dnd_has_priority_and_ends(self, engine):
        engine.ping("telegram")
        assert engine.set_dnd(minutes=30)["base"] == "dnd"
        assert engine.view()["effects"]["notify.level"] == "urgent"
        assert engine.clear_dnd()["base"] == "awake"
        assert "all" in engine.calls["release"]

    def test_core_states_cannot_be_removed_and_new_states_work(self, engine, monkeypatch):
        from core import presence_settings as PS

        custom = {"awake": {"enabled": False}, "lunch": {
            "kind": "overlay", "priority": 45, "label": "Pranzo",
            "when": [[{"signal": "clock.hour", "op": ">=", "value": 0}]], "effects": {"work.heavy": "defer"}}}
        monkeypatch.setitem(PS.settings._effective, PS.STATES, custom)
        states = engine.states()
        assert "awake" in states and states["awake"]["enabled"] is True
        engine.ping("telegram")
        assert "Pranzo" in engine.view()["label"]

    def test_disabled_means_no_effects(self, engine, monkeypatch):
        from core import presence_settings as PS

        monkeypatch.setitem(PS.settings._effective, PS.ENABLED, False)
        state = engine.view()
        assert state["base"] == "awake" and state["effects"]["work.heavy"] == "allow"

    def test_derived_signals_are_read_only(self, engine):
        with pytest.raises(ValueError):
            engine.set_signal("user.idle_minutes", 3)

    def test_change_is_emitted_once(self, engine):
        engine.ping("telegram")
        before = list(engine.calls["emit"])
        engine.ping("telegram")
        assert engine.calls["emit"] == before

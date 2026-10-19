"""Brain watch (docs/work/2026-10-19-cervello-offline §1): grace, presence signal, one notice, recovery."""
from __future__ import annotations

import pytest

from services import brain_watch


class _Presence:
    def __init__(self):
        self.calls = []

    def signal(self, key, value=True, **kw):
        self.calls.append(("signal", key, value, kw))

    def clear(self, key):
        self.calls.append(("clear", key))


@pytest.fixture
def watch(monkeypatch):
    events, presence = [], _Presence()
    monkeypatch.setattr(brain_watch, "_presence", presence)
    monkeypatch.setattr(brain_watch.hermes_client, "publish_event", lambda **kw: events.append(kw) or True)
    monkeypatch.setattr(brain_watch.cfg, "get_int", lambda key, default=0: 60)
    brain_watch.reset()
    yield events, presence
    brain_watch.reset()


@pytest.mark.unit
def test_short_outage_says_nothing(watch):
    events, presence = watch
    assert brain_watch.observe("down", now=1000) is None
    assert brain_watch.observe("down", now=1050) is None
    assert brain_watch.observe("up", now=1055) is None
    assert events == [] and presence.calls == [] and not brain_watch.is_offline()


@pytest.mark.unit
def test_offline_after_grace_one_notice_then_online(watch):
    events, presence = watch
    brain_watch.observe("down", now=1000)
    assert brain_watch.observe("down", now=1061) == "offline"
    assert brain_watch.is_offline()
    assert brain_watch.observe(None, now=1120) is None          # still offline: no second notice
    assert len(events) == 1 and events[0]["payload"]["replaces"] == "system.brain"
    assert "Cervello offline" in events[0]["payload"]["_message"]
    assert presence.calls[0][:3] == ("signal", "brain.offline", True)
    assert presence.calls[0][3]["meta"]["reason"] == "unreachable"
    assert brain_watch.observe("up", now=1000 + 14 * 60) == "online"
    back = events[-1]["payload"]
    assert back["closes"] == "system.brain" and back["decision"] == "resolved" and "14 min" in back["_message"]
    assert presence.calls[-1] == ("clear", "brain.offline")
    assert not brain_watch.is_offline()


@pytest.mark.unit
def test_signal_refreshed_while_offline(watch):
    _, presence = watch
    brain_watch.observe("down", now=0)
    brain_watch.observe("down", now=60)
    brain_watch.observe("degraded", now=60 + 601)
    signals = [c for c in presence.calls if c[0] == "signal"]
    assert len(signals) == 2 and signals[-1][3]["meta"]["reason"] == "unhealthy"


@pytest.mark.unit
def test_alerts_not_narrated_while_offline(watch, monkeypatch):
    from worker import alert_worker
    from schemas.reports import ServiceAlert
    asked = []
    monkeypatch.setattr(alert_worker.oracle_client, "analyze", lambda prompt: asked.append(prompt) or "narrated")
    brain_watch.observe("down", now=0)
    brain_watch.observe("down", now=61)
    text = alert_worker._narrate_batch([ServiceAlert(service="scout", kind="health", level="CRITICAL", message="x")])
    assert asked == [] and "scout" in text

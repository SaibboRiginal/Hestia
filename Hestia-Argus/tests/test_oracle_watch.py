"""Oracle watch (docs/work/2026-10-19-oracle-offline §1): grace, presence signal, one notice, recovery."""
from __future__ import annotations

import pytest

from services import oracle_watch


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
    monkeypatch.setattr(oracle_watch, "_presence", presence)
    monkeypatch.setattr(oracle_watch.hermes_client, "publish_event", lambda **kw: events.append(kw) or True)
    monkeypatch.setattr(oracle_watch.cfg, "get_int", lambda key, default=0: 60)
    oracle_watch.reset()
    yield events, presence
    oracle_watch.reset()


@pytest.mark.unit
def test_short_outage_says_nothing(watch):
    events, presence = watch
    assert oracle_watch.observe("down", now=1000) is None
    assert oracle_watch.observe("down", now=1050) is None
    assert oracle_watch.observe("up", now=1055) is None
    assert events == [] and presence.calls == [] and not oracle_watch.is_offline()


@pytest.mark.unit
def test_offline_after_grace_one_notice_then_online(watch):
    events, presence = watch
    oracle_watch.observe("down", now=1000)
    assert oracle_watch.observe("down", now=1061) == "offline"
    assert oracle_watch.is_offline()
    assert oracle_watch.observe(None, now=1120) is None          # still offline: no second notice
    assert len(events) == 1 and events[0]["payload"]["replaces"] == "system.oracle"
    assert "Non disponibile" in events[0]["payload"]["_message"]
    assert presence.calls[0][:3] == ("signal", "oracle.offline", True)
    assert presence.calls[0][3]["meta"]["reason"] == "unreachable"
    assert oracle_watch.observe("up", now=1000 + 14 * 60) == "online"
    back = events[-1]["payload"]
    assert back["closes"] == "system.oracle" and back["decision"] == "resolved" and "14 min" in back["_message"]
    assert presence.calls[-1] == ("clear", "oracle.offline")
    assert not oracle_watch.is_offline()


@pytest.mark.unit
def test_signal_refreshed_while_offline(watch):
    _, presence = watch
    oracle_watch.observe("down", now=0)
    oracle_watch.observe("down", now=60)
    oracle_watch.observe("degraded", now=60 + 601)
    signals = [c for c in presence.calls if c[0] == "signal"]
    assert len(signals) == 2 and signals[-1][3]["meta"]["reason"] == "unhealthy"


@pytest.mark.unit
def test_alerts_not_narrated_while_offline(watch, monkeypatch):
    from worker import alert_worker
    from schemas.reports import ServiceAlert
    asked = []
    monkeypatch.setattr(alert_worker.oracle_client, "analyze", lambda prompt: asked.append(prompt) or "narrated")
    oracle_watch.observe("down", now=0)
    oracle_watch.observe("down", now=61)
    text = alert_worker._narrate_batch([ServiceAlert(service="scout", kind="health", level="CRITICAL", message="x")])
    assert asked == [] and "scout" in text

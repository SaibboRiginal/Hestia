"""Immune system (v3 B) and the journal in Archive (v3 F) — docs/work/2026-10-19-oracle-offline."""
from __future__ import annotations

import threading

import pytest

from services import health_history, immune


class _SyncThread:
    """Run the restart at once (no real thread) so the test sees its effects."""

    def __init__(self, target=None, args=(), **kw):
        self._t, self._a = target, args

    def start(self):
        self._t(*self._a)


@pytest.fixture
def env(monkeypatch):
    events, restarts = [], []
    result = {"status": "ok", "restarted": True, "healthy": False}
    settings = {immune.cfg.REPAIR_RESTARTS: 3, immune.cfg.REPAIR_RESTART_AFTER: 120}
    monkeypatch.setattr(immune.cfg, "get_int", lambda key, default=0: settings.get(key, default))
    monkeypatch.setattr(immune.cfg, "get_bool", lambda key: True)
    monkeypatch.setattr(immune.hermes_client, "publish_event", lambda **kw: events.append(kw) or True)

    def route(service, path, method="GET", body=None, **kw):
        restarts.append((service, path, body))
        return True, dict(result)

    monkeypatch.setattr(immune.hub_client, "route", route)
    monkeypatch.setattr(immune.threading, "Thread", _SyncThread)
    immune.reset()
    health_history.reset()
    yield events, restarts, result, settings
    immune.reset()
    health_history.reset()


@pytest.mark.unit
def test_short_outage_is_not_restarted(env):
    events, restarts, _, _ = env
    assert immune.observe("hecate", False, now=1000) is None
    assert immune.observe("hecate", False, now=1100) is None
    assert immune.observe("hecate", True, now=1110) is None
    assert restarts == [] and events == []


@pytest.mark.unit
def test_three_restarts_with_growing_waits_then_one_notice(env):
    events, restarts, _, _ = env
    health_history.note_unhealthy("hecate", "down", "refused")
    assert immune.observe("hecate", False, now=1000) is None
    assert immune.observe("hecate", False, now=1120) == "restart"       # after 120 s
    assert restarts[-1] == ("hephaestus", "api/hephaestus/restart", {"service": "hecate", "reason": "argus.immune", "attempt": 1})
    assert immune.observe("hecate", False, now=1300) is None            # waits 240 s now
    assert immune.observe("hecate", False, now=1360) == "restart"
    assert immune.observe("hecate", False, now=1840) == "restart"       # +480 s
    assert immune.observe("hecate", False, now=2800) == "gave_up"       # +960 s, 3 tries used
    assert immune.observe("hecate", False, now=9999) is None            # no more tries, no second notice
    assert len(restarts) == 3 and len(events) == 1
    assert events[0]["payload"]["replaces"] == "system.repair.hecate"
    assert "hecate" not in events[0]["payload"]["_message"]             # generic user text
    kinds = [a["kind"] for a in health_history.incidents()["open"][0]["actions"]]
    assert kinds.count("restart") == 3 and kinds[-1] == "gave_up"
    assert immune.observe("hecate", True, now=10000) == "recovered"
    assert events[-1]["payload"]["closes"] == "system.repair.hecate"


@pytest.mark.unit
def test_healthy_after_restart_resets(env):
    events, restarts, result, _ = env
    result["healthy"] = True
    immune.observe("plutus", False, now=0)
    assert immune.observe("plutus", False, now=200) == "restart"
    assert immune.observe("plutus", True, now=260) == "recovered"
    assert events == []                                                 # no gave-up notice to close
    assert immune.observe("plutus", False, now=300) is None             # a new outage starts again from zero


@pytest.mark.unit
def test_never_restarts_itself_hephaestus_or_hub_and_respects_zero(env):
    _, restarts, _, settings = env
    for svc in ("argus", "hephaestus", "hub"):
        immune.observe(svc, False, now=0)
        assert immune.observe(svc, False, now=10000) is None
    settings[immune.cfg.REPAIR_RESTARTS] = 0
    immune.observe("hecate", False, now=0)
    assert immune.observe("hecate", False, now=10000) is None
    assert restarts == []


@pytest.mark.unit
def test_forge_deploy_window_does_not_use_a_try(env):
    _, restarts, result, _ = env
    result.update(status="skipped", restarted=False)
    immune.observe("hecate", False, now=0)
    assert immune.observe("hecate", False, now=200) == "restart"
    assert immune.snapshot()["hecate"]["attempts"] == 0


@pytest.mark.unit
def test_journal_written_to_archive_and_reloaded(monkeypatch):
    health_history.reset()
    store: dict[str, dict] = {}
    monkeypatch.setattr(health_history.threading, "Thread", _SyncThread)

    def route(service, path, method="GET", body=None, query=None, **kw):
        assert (service, path) == ("archive", "api/argus-store/records")
        if method == "PUT":
            for row in body["rows"]:
                store[row["id"]] = row
            return True, {"applied": []}
        return True, {"rows": sorted(store.values(), key=lambda r: r["at"], reverse=True)}

    health_history.start_journal(route)
    health_history.note_unhealthy("hecate", "down", "refused")
    health_history.note_action("hecate", "restart", "Riavvio automatico 1/3")
    health_history.note_recovered("hecate")
    health_history.note_unhealthy("scout", "down", None)
    assert len(store) == 2
    saved = next(r for r in store.values() if r["ref_id"] == "hecate")
    assert saved["kind"] == "incident" and saved["data"]["closed_at"]
    assert [a["kind"] for a in saved["data"]["actions"]] == ["detected", "restart", "recovered"]

    health_history.reset()                       # Argus restarts
    assert health_history.start_journal(route) == 2
    inc = health_history.incidents(limit=10)
    assert [i["service"] for i in inc["recent"]] == ["hecate"] and health_history.is_open("scout")
    health_history.reset()

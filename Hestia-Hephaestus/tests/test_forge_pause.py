"""Forge manual pause (Themis hephaestus.forge.paused): nothing starts on its own."""
from __future__ import annotations

import queue
import threading
from types import SimpleNamespace

import pytest

from app.forge import forge_settings
from app.forge import service as forge_service
from app.forge.service import Forge

pytestmark = pytest.mark.unit


class _Pool:
    def submit(self, *_a, **_k):
        return None


def _forge(monkeypatch, paused: bool) -> Forge:
    forge = Forge.__new__(Forge)
    forge.cfg = SimpleNamespace(enabled=True, repo_path="/repo", notify_target="owner")
    forge.engines = {}
    forge._lock = threading.RLock()
    forge._tasks = {}
    forge._queue = queue.Queue()
    forge._default_engine = "local"
    forge._modes = {"local": "auto", "cloud": "ask"}
    forge._agenda_pool = _Pool()
    forge.notified = []
    monkeypatch.setattr(forge_service.git_ops, "is_repo", lambda _p: True)
    monkeypatch.setattr(Forge, "_save", lambda self: None)
    monkeypatch.setattr(Forge, "_engine_name_for", lambda self, _e: "local")
    monkeypatch.setattr(Forge, "_notify", lambda self, task, text: self.notified.append(text))
    monkeypatch.setattr(forge_settings.settings, "get",
                        lambda key, default=None: paused if key == forge_settings.PAUSED
                        else forge_settings.settings._defs[key]["default"])
    return forge


def test_paused_holds_autonomous_task_silently(monkeypatch):
    forge = _forge(monkeypatch, paused=True)
    task = forge.submit(request="Audit della pipeline MCP", source="athena", requested_by="athena")
    assert task["state"] == "proposed"
    assert task["held_by_pause"] is True
    assert forge._queue.empty()
    assert forge.notified == []


def test_paused_still_starts_user_request(monkeypatch):
    forge = _forge(monkeypatch, paused=True)
    task = forge.submit(request="Aggiungi export ICS", source="ui")
    assert task["state"] == "queued"
    assert forge._queue.get_nowait() == task["id"]


def test_not_paused_autonomous_task_starts_in_auto_mode(monkeypatch):
    forge = _forge(monkeypatch, paused=False)
    task = forge.submit(request="Audit della pipeline MCP", source="athena")
    assert task["state"] == "queued"


def test_manual_approve_overrides_pause(monkeypatch):
    forge = _forge(monkeypatch, paused=True)
    task = forge.submit(request="Audit della pipeline MCP", source="argus")
    forge.approve(task["id"])
    assert task["state"] == "queued"
    assert task["manual_start"] is True
    assert "held_by_pause" not in task
    assert not forge._autonomous(task)


# ── duplicates and engine choice (same file: same Forge stub) ──────────────
def test_module_duplicate_within_days_is_not_created_again(monkeypatch):
    forge = _forge(monkeypatch, paused=True)
    first = forge.submit(request="Audit della pipeline di ingestione MCP", source="athena")
    again = forge.submit(request="Audit pipeline di ingestione MCP", source="athena")
    assert again["id"] == first["id"] and again["duplicate"] is True
    assert len(forge._tasks) == 1


def test_different_error_same_template_is_not_a_duplicate(monkeypatch):
    forge = _forge(monkeypatch, paused=True)
    req = "Fix recurring error in service 'scout'. Find root cause, fix, add regression test."
    forge.submit(request=req, services=["scout"], source="argus", context="signature=aaa\nlog:\nKeyError price")
    other = forge.submit(request=req, services=["scout"], source="argus",
                         context="signature=bbb\nlog:\nTimeout calling idealista listing endpoint")
    assert not other.get("duplicate")
    assert len(forge._tasks) == 2


def test_user_requests_are_never_deduplicated(monkeypatch):
    forge = _forge(monkeypatch, paused=False)
    a = forge.submit(request="Aggiungi export ICS", source="ui")
    b = forge.submit(request="Aggiungi export ICS", source="ui")
    assert a["id"] != b["id"]


def test_approve_with_engine_choice(monkeypatch):
    forge = _forge(monkeypatch, paused=True)
    forge.engines = {"local": object(), "claude": object()}
    task = forge.submit(request="Audit della pipeline MCP", source="athena")
    forge.approve(task["id"], engine="claude")
    assert task["engine_requested"] == "claude"
    assert task["budgeted"] is False
    assert task["state"] == "queued"

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

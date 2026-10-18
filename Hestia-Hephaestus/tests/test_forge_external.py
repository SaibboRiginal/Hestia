"""Forge for external AIs (docs/work/2026-10-18-moduli-core-e-mcp-esterno §B4): notes on a task, "I fixed it on
this branch" (fetch → Forge's tests → owner approval), requests marked as external proposals."""
from __future__ import annotations

import queue
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.forge import forge_settings
from app.forge import service as forge_service
from app.forge.router import create_forge_router
from app.forge.service import Forge, ForgeError, notes_text

pytestmark = pytest.mark.unit


class _Pool:
    def submit(self, *_a, **_k):
        return None


class _Agenda:
    def hide_task(self, *_a, **_k):
        return None


def _forge(monkeypatch, tmp_path: Path | None = None, repo: Path | None = None) -> Forge:
    forge = Forge.__new__(Forge)
    forge.cfg = SimpleNamespace(enabled=True, repo_path=repo or Path("/repo"), notify_target="owner",
                                worktrees_path=(tmp_path or Path("/tmp")) / "worktrees", base_branch="main")
    forge.engines = {}
    forge._lock = threading.RLock()
    forge._tasks = {}
    forge._queue = queue.Queue()
    forge._default_engine = "local"
    forge._modes = {"local": "ask", "cloud": "ask"}
    forge._agenda_pool = _Pool()
    forge.agenda = _Agenda()
    forge.notified = []
    if repo is None:
        monkeypatch.setattr(forge_service.git_ops, "is_repo", lambda _p: True)
    monkeypatch.setattr(Forge, "_save", lambda self: None)
    monkeypatch.setattr(Forge, "_engine_name_for", lambda self, _e: "local")
    monkeypatch.setattr(Forge, "_notify", lambda self, task, text: self.notified.append(text))
    monkeypatch.setattr(forge_settings.settings, "get",
                        lambda key, default=None: forge_settings.settings._defs[key]["default"])
    return forge


def _failed_task(forge: Forge) -> dict:
    task = forge.submit(request="Correggi il bug del calendario", source="ui")
    forge._queue.get_nowait()
    task["state"] = "failed"
    return task


def test_notes_are_kept_and_reach_the_engine_context(monkeypatch):
    forge = _forge(monkeypatch)
    task = _failed_task(forge)
    forge.add_note(task["id"][:6], "Causa: timezone UTC in Archive", by="Claude Code PC")
    assert task["notes"][-1]["by"] == "Claude Code PC"
    assert "timezone UTC" in notes_text(task)
    retry = forge.retry(task["id"])
    assert "timezone UTC" in retry["context"]
    with pytest.raises(ForgeError):
        forge.add_note(task["id"], " ")


def test_submit_branch_checks_name_and_state_then_queues(monkeypatch):
    forge = _forge(monkeypatch)
    task = _failed_task(forge)
    for bad in ("", "-x", "a..b", "auto/forge/abc", "fix/", "x.lock"):
        with pytest.raises(ForgeError):
            forge.submit_branch(task["id"], bad)
    forge.submit_branch(task["id"], "claude/fix-calendar", "fix tz", by="Claude Code PC")
    assert task["state"] == "queued" and forge._queue.get_nowait() == task["id"]
    assert task["external"]["pending"] is True and task["auto_merge"] is False
    with pytest.raises(ForgeError) as exc:
        forge.submit_branch(task["id"], "claude/fix-calendar")   # queued: not now
    assert exc.value.status_code == 409


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_run_external_fetches_the_branch_into_the_task_worktree(monkeypatch, tmp_path):
    origin, repo, other = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "other"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    for cwd in (repo,):
        _git(cwd, "config", "user.email", "t@t"), _git(cwd, "config", "user.name", "t")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A"), _git(repo, "commit", "-qm", "init"), _git(repo, "push", "-q", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "t@t"), _git(other, "config", "user.name", "t")
    _git(other, "checkout", "-qb", "claude/fix")
    (other / "a.txt").write_text("two\n")
    _git(other, "commit", "-qam", "fix"), _git(other, "push", "-q", "origin", "claude/fix")

    forge = _forge(monkeypatch, tmp_path, repo=repo)
    reviewed = []
    monkeypatch.setattr(Forge, "_review", lambda self, task, wt, base, sha, summary, ok, heading="":
                        reviewed.append((Path(wt), base, sha, summary, heading)))
    task = _failed_task(forge)
    forge.submit_branch(task["id"], "claude/fix", "a.txt corretto", by="Claude Code PC")
    forge._run_external(task)
    wt, base, sha, summary, heading = reviewed[-1]
    assert (wt / "a.txt").read_text() == "two\n" and sha == _git(other, "rev-parse", "HEAD")
    assert base == _git(repo, "rev-parse", "main") and "Claude Code PC" in heading
    assert task["engine"] == "external" and task["external"]["pending"] is False

    task["state"] = "awaiting_review"   # what _review leaves (stubbed here)
    forge.submit_branch(task["id"], "does-not-exist")
    forge._run_external(task)
    assert task["state"] == "failed" and "does-not-exist" in forge.notified[-1]


def test_request_from_an_external_ai_is_an_external_proposal(monkeypatch):
    forge = _forge(monkeypatch)
    app = FastAPI()
    app.include_router(create_forge_router(forge))
    c = TestClient(app)
    body = {"request": "Aggiungi un widget meteo", "auto_start": True, "auto_merge": True, "source": "user"}
    out = c.post("/api/hephaestus/forge/tasks", json=body, headers={"X-Hestia-Access": "Cursor"}).json()["task"]
    task = forge.get(out["id"])
    assert task["source"] == "external" and task["requested_by"] == "Cursor"
    assert task["state"] == "proposed" and task["auto_merge"] is False   # mode "ask": waits for the owner
    note = c.post(f"/api/hephaestus/forge/tasks/{task['id']}/notes", json={"text": "vedi Hestia-Iris"},
                  headers={"X-Hestia-Access": "Cursor"}).json()
    assert note["notes"] == 1 and forge.get(task["id"])["notes"][0]["by"] == "Cursor"
    view = c.get(f"/api/hephaestus/forge/tasks/{task['id'][:6]}/overview").json()["task"]
    assert view["notes"][0]["text"] == "vedi Hestia-Iris" and view["history"]

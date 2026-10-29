"""Forge automatic review, team plan and Claude-limit wait (docs/work/2026-10-24-tutto-brainstorm-cindy W3:
Cindy 3, 15, 31). Git, tests and the model are stubbed."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.forge import forge_settings
from app.forge import review as forge_review
from app.forge import service as forge_service
from app.forge.engines import EngineResult
from app.forge.service import Forge

pytestmark = pytest.mark.unit


class _Pool:
    def submit(self, *_a, **_k):
        return None


class _Agenda:
    def __init__(self):
        self.planned = []

    def hide_task(self, *_a, **_k):
        return None

    def plan(self, key, title, start_at, **kw):
        self.planned.append((key, kw.get("action")))


class _Engine:
    def __init__(self, name, ok=True):
        self.name, self.ok, self.prompts = name, ok, []

    def available(self):
        return True, "ok"

    def run(self, workdir, prompt, test_runner, on_event=None):
        self.prompts.append(prompt)
        return EngineResult(self.ok, f"{self.name} fatto", self.name)


class _Artifacts:
    def __getattr__(self, _name):
        return lambda *a, **k: None


class _Reviewer:
    def __init__(self, reviews, pieces=None):
        self.reviews, self.pieces = list(reviews), pieces or []

    def review(self, **_kw):
        return self.reviews.pop(0)

    def plan(self, *_a):
        return self.pieces


def _forge(monkeypatch, tmp_path) -> Forge:
    forge = Forge.__new__(Forge)
    forge.cfg = SimpleNamespace(enabled=True, repo_path=Path("/repo"), notify_target="owner", test_cmd="pytest",
                                worktrees_path=tmp_path / "worktrees", base_branch="main", git_author_name="f",
                                git_author_email="f@f", hub_api_url="http://hub/api")
    forge.engines = {}
    forge._lock = threading.RLock()
    forge._tasks = {}
    forge._queue = queue.Queue()
    forge._default_engine = "oracle"
    forge._modes = {"local": "ask", "cloud": "ask"}
    forge._agenda_pool = _Pool()
    forge.agenda = _Agenda()
    forge.artifacts = _Artifacts()
    forge.presence = SimpleNamespace(signal=lambda *a, **k: None)
    forge.claude_budget = SimpleNamespace(mark_exhausted=lambda: "2026-10-25T05:00:00+00:00",
                                          looks_like_limit=lambda text: "limit" in text)
    forge.notified = []
    monkeypatch.setattr(Forge, "_save", lambda self: None)
    monkeypatch.setattr(Forge, "_save_settings", lambda self: None)
    monkeypatch.setattr(Forge, "_notify", lambda self, task, text: self.notified.append(text))
    monkeypatch.setattr(Forge, "_cleanup", lambda self, task, delete_branch: None)
    monkeypatch.setattr(forge_settings.settings, "get",
                        lambda key, default=None: forge_settings.settings._defs[key]["default"])
    g = forge_service.git_ops
    monkeypatch.setattr(g, "changed_files", lambda wt, base: ["Hestia-Chronos/app/x.py"])
    monkeypatch.setattr(g, "diff_stat", lambda wt, base: "1 file")
    monkeypatch.setattr(g, "diff", lambda wt, base, max_chars=0: "+x")
    monkeypatch.setattr(g, "rev", lambda wt, ref="HEAD": "head")
    monkeypatch.setattr(g, "git", lambda *a, **k: "")
    monkeypatch.setattr(forge_service, "run_test_command", lambda *a, **k: (True, "1 passed"))
    return forge


def _task(forge, **extra):
    task = {"id": "abc123", "request": "Aggiungi X", "services": ["chronos"], "state": "running",
            "branch": "auto/forge/abc123", "base_sha": "base", "history": [], **extra}
    forge._tasks[task["id"]] = task
    return task


def test_reviewer_parses_issues_and_counts_blocking(monkeypatch):
    r = forge_review.ForgeReviewer("http://hub/api")
    monkeypatch.setattr(r, "_generate", lambda uc, prompt: (
        'Ecco: {"verdict": "problemi", "issues": [{"priority": "alta", "file": "a.py", "problem": "manca il test"},'
        '{"priority": "bassa", "file": "b.py", "problem": "nome"}, {"problem": ""}]}'))
    out = r.review(request="r", acceptance="a", diff="d", tests="t", summary="s")
    assert out["verdict"] == "problemi" and out["blocking"] == 1 and len(out["issues"]) == 2


def test_reviewer_unreachable_never_blocks(monkeypatch):
    r = forge_review.ForgeReviewer("http://hub/api")
    monkeypatch.setattr(r, "_generate", lambda uc, prompt: None)
    out = r.review(request="r", acceptance="a", diff="d", tests="t", summary="s")
    assert out == {"verdict": "non_disponibile", "issues": [], "blocking": 0}
    assert "non disponibile" in forge_review.card(out)


def test_review_prompt_marks_the_engine_story_as_unverified():
    assert "autodichiarazione non verificata" in forge_review.REVIEW_PROMPT


def test_blocking_issues_get_one_round_of_fixes(monkeypatch, tmp_path):
    forge = _forge(monkeypatch, tmp_path)
    issue = {"priority": "alta", "file": "x.py", "problem": "bug", "evidence": ""}
    forge.reviewer = _Reviewer([{"verdict": "problemi", "issues": [issue], "blocking": 1},
                                {"verdict": "ok", "issues": [], "blocking": 0}])
    commits = iter(["fix-sha"])
    monkeypatch.setattr(forge_service.git_ops, "commit_all", lambda *a, **k: next(commits, None))
    engine = _Engine("oracle")
    task = _task(forge)
    forge._review(task, tmp_path, "base", "sha1", "fatto", True, engine=engine, test_runner=None)
    assert "revisione automatica" in engine.prompts[0] and "bug" in engine.prompts[0]
    assert task["state"] == "awaiting_review" and task["commit_sha"] == "fix-sha"
    assert task["review"]["rounds"] == 1 and task["review"]["verdict"] == "ok"
    assert "Revisione automatica" in forge.notified[-1]


def test_auto_merge_waits_when_blocking_issues_remain(monkeypatch, tmp_path):
    forge = _forge(monkeypatch, tmp_path)
    issue = {"priority": "media", "file": "x.py", "problem": "bug", "evidence": ""}
    forge.reviewer = _Reviewer([{"verdict": "problemi", "issues": [issue], "blocking": 1}])
    merged = []
    monkeypatch.setattr(Forge, "_merge_and_deploy", lambda self, task, by: merged.append(by))
    task = _task(forge, auto_merge=True)
    forge._review(task, tmp_path, "base", "sha1", "fatto", True)          # external branch: no fix round
    assert task["state"] == "awaiting_review" and merged == []


def test_claude_limit_waits_and_plans_a_resume(monkeypatch, tmp_path):
    forge = _forge(monkeypatch, tmp_path)
    monkeypatch.setattr(forge_service.git_ops, "commit_all", lambda *a, **k: "partial")
    task = _task(forge)
    engine = _Engine("claude", ok=False)
    engine.run = lambda *a, **k: EngineResult(False, "usage limit reached", "claude")
    assert forge._engine_pass(task, engine, tmp_path, "p", None) is None
    assert task["state"] == "waiting_limit" and task["resume_from"] == "head"
    key, action = forge.agenda.planned[-1]
    assert key == "forge.resume.abc123" and action["path"].endswith("/tasks/abc123/resume")
    forge.resume("abc123")
    assert task["state"] == "queued" and forge._queue.get_nowait() == "abc123"


def test_three_limits_without_progress_fail(monkeypatch, tmp_path):
    forge = _forge(monkeypatch, tmp_path)
    monkeypatch.setattr(forge_service.git_ops, "commit_all", lambda *a, **k: None)
    task = _task(forge, resume_from="head", limit_restarts=2)
    forge._wait_for_limit(task, tmp_path)
    assert task["state"] == "failed"


def test_team_pieces_use_the_engine_of_their_difficulty(monkeypatch, tmp_path):
    forge = _forge(monkeypatch, tmp_path)
    local, claude = _Engine("oracle"), _Engine("claude")
    forge.engines = {"oracle": local, "claude": claude}
    assert forge._engine_for_piece({"difficulty": "semplice"}, claude) is local
    assert forge._engine_for_piece({"difficulty": "difficile"}, local) is claude
    forge.reviewer = _Reviewer([], pieces=[{"title": "a", "request": "x", "difficulty": "semplice", "services": []}])
    assert forge._team_plan({"services": ["a"], "request": "r"}) == []          # below the threshold (3)
    assert len(forge._team_plan({"services": ["a", "b", "c"], "request": "r"})) == 1

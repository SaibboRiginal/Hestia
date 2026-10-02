"""Forge — Hestia develops itself.

State machine (persisted to JSON, survives restarts):

    proposed ──approve──► queued ──► running ──► awaiting_review ──approve──► merged ──► deployed
        │                                │              │                        │
        └──reject──► rejected            └► failed      └──reject──► rejected    └──rollback──► rolled_back

- Every task runs in its own git worktree + branch ``auto/forge/<id>``: the live
  checkout is never touched until merge.
- Forge runs tests itself after the engine (never trusts the agent's word).
- Merge = ``git merge --no-ff`` into the base branch; rollback = ``git revert -m 1``.
- Deploy (optional) = ``HEPHAESTUS_FORGE_DEPLOY_CMD``; then health check via Hub;
  unhealthy + auto_rollback → revert + redeploy.
- Pre-change notice, review request, post-change summary and rollback are all
  pushed to the user (Hermes).
"""
from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from . import git_ops
from .agent_tools import run_test_command
from .config import ForgeConfig, normalize_engine
from .engines import build_engines, select_engine, wait_seconds
from .prompts import build_task_prompt

logger = logging.getLogger("hestia_hephaestus.forge")

ACTIVE_STATES = {"queued", "running", "approved", "merging"}
TERMINAL_STATES = {"failed", "rejected", "rolled_back", "deployed", "merged", "no_changes"}


class ForgeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def services_from_paths(paths: list[str]) -> list[str]:
    """``Hestia-Hecate/app/main.py`` → ``hecate`` (compose/Hub service name)."""
    found: list[str] = []
    for path in paths:
        top = path.split("/", 1)[0]
        if top.startswith("Hestia-") and top not in {"Hestia-Swagger", "Hestia-Shared"}:
            name = top[len("Hestia-"):].lower()
            if name not in found:
                found.append(name)
    return found


class Forge:
    def __init__(self, cfg: ForgeConfig):
        self.cfg = cfg
        self.engines = build_engines(cfg)
        self._lock = threading.RLock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._default_engine = cfg.engine
        self._load()
        self._load_settings()

    # ── persistence ─────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if self.cfg.state_file.exists():
                data = json.loads(self.cfg.state_file.read_text(encoding="utf-8") or "{}")
                self._tasks = {t["id"]: t for t in data.get("tasks", []) if isinstance(t, dict) and t.get("id")}
        except Exception as exc:
            logger.warning("[🔄] event=forge_state_load_failed path=%s error=%s", self.cfg.state_file, exc)

    def _load_settings(self) -> None:
        try:
            if self.cfg.settings_file.exists():
                data = json.loads(self.cfg.settings_file.read_text(encoding="utf-8") or "{}")
                engine = normalize_engine(data.get("default_engine", ""))
                if engine in self.engines:
                    self._default_engine = engine
        except Exception as exc:
            logger.warning("[🔄] event=forge_settings_load_failed error=%s", exc)

    @property
    def default_engine(self) -> str:
        return self._default_engine

    def set_default_engine(self, engine: str) -> dict[str, Any]:
        """Switch the default engine at runtime (persisted, survives restarts)."""
        name = normalize_engine(engine)
        if name not in self.engines:
            raise ForgeError(f"Unknown engine '{engine}'. Use: {', '.join(self.engines)}")
        ok, reason = self.engines[name].available()
        self._default_engine = name
        try:
            self.cfg.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.cfg.settings_file.write_text(json.dumps({"default_engine": name}), encoding="utf-8")
        except Exception as exc:
            logger.warning("[🔄] event=forge_settings_save_failed error=%s", exc)
        logger.info("event=forge_default_engine_set engine=%s available=%s", name, ok)
        return {"default_engine": name, "available": ok, "detail": reason}

    def _save(self) -> None:
        with self._lock:
            payload = {"tasks": sorted(self._tasks.values(), key=lambda t: t["created_at"])[-200:]}
        try:
            self.cfg.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cfg.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cfg.state_file)
        except Exception as exc:
            logger.warning("[🔄] event=forge_state_save_failed error=%s", exc)

    def _set_state(self, task: dict, state: str, note: str = "") -> None:
        with self._lock:
            task["state"] = state
            task["updated_at"] = _now()
            task.setdefault("history", []).append({"ts": task["updated_at"], "state": state, "note": note[:500]})
        logger.info("event=forge_state task_id=%s state=%s note=%s", task["id"], state, note[:200])
        self._save()

    # ── lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        # Resilience: resume anything interrupted by a restart.
        with self._lock:
            for task in self._tasks.values():
                if task.get("state") in {"queued", "running"}:
                    task["state"] = "queued"
                    self._queue.put(task["id"])
                elif task.get("state") in {"approved", "merging"} and not task.get("merge_sha"):
                    task["state"] = "approved"
                    self._queue.put(task["id"])
        self._worker = threading.Thread(target=self._work_loop, daemon=True, name="forge-worker")
        self._worker.start()
        logger.info("event=forge_started repo=%s default_engine=%s", self.cfg.repo_path, self._default_engine)

    def _work_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            task = self.get(task_id)
            if not task or task.get("state") not in {"queued", "approved"}:
                continue
            try:
                if task["state"] == "approved":
                    self._merge_and_deploy(task, task.get("approved_by", "user"))
                else:
                    self._run_task(task)
            except Exception as exc:
                logger.exception("[🔄] event=forge_task_crashed task_id=%s", task_id)
                task["error"] = str(exc)[:1000]
                self._set_state(task, "failed", f"crash: {exc}")
                self._notify(task, f"❌ Forge task <code>{task_id}</code> fallito: {exc}")

    # ── public API ──────────────────────────────────────────────────────────
    def status(self) -> dict[str, Any]:
        engines = {}
        for name, engine in self.engines.items():
            ok, reason = engine.available()
            engines[name] = {"available": ok, "detail": reason}
        repo_ok = git_ops.is_repo(self.cfg.repo_path)
        return {
            "enabled": self.cfg.enabled,
            "repo_path": str(self.cfg.repo_path),
            "repo_ok": repo_ok,
            "base_branch": self._base_branch() if repo_ok else None,
            "engine_default": self._default_engine,
            "engine_fallback": self.cfg.fallback,
            "engines": engines,
            "auto_merge": self.cfg.auto_merge,
            "deploy_enabled": bool(self.cfg.deploy_cmd),
            "queue": [t["id"] for t in self.list(state="queued")],
        }

    def list(self, state: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(t) for t in self._tasks.values()]
        if state:
            rows = [t for t in rows if t.get("state") == state]
        rows.sort(key=lambda t: t["created_at"], reverse=True)
        for row in rows:
            row.pop("history", None)
        return rows[:max(1, min(limit, 200))]

    def get(self, task_id: str) -> dict[str, Any] | None:
        task_id = str(task_id or "").strip()
        with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id]
            # Accept short ids typed by humans ("a1b2c3").
            matches = [t for tid, t in self._tasks.items() if tid.startswith(task_id)] if len(task_id) >= 4 else []
        return matches[0] if len(matches) == 1 else None

    def submit(self, *, request: str, services: list[str] | None = None, engine: str = "",
               source: str = "user", requested_by: str = "user", auto_start: bool = True,
               auto_merge: bool | None = None, context: str = "", notify_target: str = "") -> dict[str, Any]:
        if not self.cfg.enabled:
            raise ForgeError("Forge disabled (HEPHAESTUS_FORGE_ENABLED=0)", 503)
        if not git_ops.is_repo(self.cfg.repo_path):
            raise ForgeError(f"Repo not mounted at {self.cfg.repo_path} (volume ./:/repo)", 503)
        request = str(request or "").strip()
        if len(request) < 8:
            raise ForgeError("Request too short: describe what to build or fix")
        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "request": request[:4000],
            "services": [s.strip().lower() for s in (services or []) if str(s).strip()],
            "engine_requested": normalize_engine(engine) or "auto",
            "source": source,
            "requested_by": requested_by,
            "context": str(context or "")[:4000],
            "auto_merge": self.cfg.auto_merge if auto_merge is None else bool(auto_merge),
            "notify_target": notify_target or self.cfg.notify_target,
            "branch": f"auto/forge/{task_id}",
            "created_at": _now(),
            "updated_at": _now(),
            "state": "new",
            "history": [],
        }
        with self._lock:
            self._tasks[task_id] = task
        if auto_start:
            self._enqueue(task, f"submitted by {requested_by} ({source})")
        else:
            self._set_state(task, "proposed", f"proposed by {source}")
            self._notify(task, (
                f"💡 <b>Proposta di sviluppo</b> <code>{task_id[:6]}</code>\n{_esc(request[:600])}\n\n"
                f"Rispondi \"approva sviluppo {task_id[:6]}\" per avviarla, \"rifiuta {task_id[:6]}\" per scartarla."))
        return task

    def approve(self, task_id: str, approved_by: str = "user") -> dict[str, Any]:
        task = self._require(task_id)
        state = task.get("state")
        if state == "proposed":
            self._enqueue(task, f"start approved by {approved_by}")
            return task
        if state == "awaiting_review":
            self._check_mergeable(task)   # fail fast, synchronously
            with self._lock:
                task["approved_by"] = approved_by
            self._set_state(task, "approved", f"merge approved by {approved_by}")
            self._queue.put(task["id"])
            return task
        raise ForgeError(f"Task in state '{state}': nothing to approve")

    def reject(self, task_id: str, reason: str = "", rejected_by: str = "user") -> dict[str, Any]:
        task = self._require(task_id)
        if task.get("state") not in {"proposed", "awaiting_review", "failed", "no_changes"}:
            raise ForgeError(f"Task in state '{task.get('state')}' cannot be rejected")
        self._cleanup(task, delete_branch=True)
        self._set_state(task, "rejected", f"by {rejected_by}: {reason}")
        return task

    def rollback(self, task_id: str, reason: str = "", requested_by: str = "user") -> dict[str, Any]:
        task = self._require(task_id)
        if task.get("state") not in {"merged", "deployed"} or not task.get("merge_sha"):
            raise ForgeError(f"Task in state '{task.get('state')}' has nothing to roll back")
        self._do_rollback(task, f"by {requested_by}: {reason}")
        return task

    def diff(self, task_id: str) -> str:
        task = self._require(task_id)
        base = task.get("base_sha")
        if not base:
            return ""
        worktree = Path(task.get("worktree") or "")
        if worktree.exists():
            return git_ops.diff(worktree, base)
        head = task.get("merge_sha") or task.get("commit_sha")
        return git_ops.diff(self.cfg.repo_path, base, head) if head else ""

    # ── internals ───────────────────────────────────────────────────────────
    def _require(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            raise ForgeError(f"Task '{task_id}' not found", 404)
        return task

    def _enqueue(self, task: dict, note: str) -> None:
        self._set_state(task, "queued", note)
        self._queue.put(task["id"])

    def _base_branch(self) -> str:
        return self.cfg.base_branch or git_ops.current_branch(self.cfg.repo_path)

    def _test_paths(self, root: Path, changed: list[str], services: list[str]) -> list[str]:
        names = services_from_paths(changed) or services
        folders = {p.name.lower(): p.name for p in root.glob("Hestia-*") if p.is_dir()}
        paths = []
        for name in names:
            folder = folders.get(f"hestia-{name.lower()}")
            if folder and (root / folder / "tests").is_dir():
                paths.append(f"{folder}/tests")
        return paths

    def _run_task(self, task: dict) -> None:
        repo = self.cfg.repo_path
        engine, reason = select_engine(self.engines, task.get("engine_requested", "auto"),
                                       self._default_engine, self.cfg.fallback)
        if engine is None:
            task["error"] = reason
            self._set_state(task, "failed", reason)
            self._notify(task, f"❌ Forge: nessun motore disponibile — {_esc(reason)}")
            return

        worktree = self.cfg.worktrees_path / task["id"]
        self._cleanup(task, delete_branch=True)  # idempotent restart
        base_branch = self._base_branch()
        base_sha = git_ops.rev(repo, base_branch)
        git_ops.create_worktree(repo, worktree, task["branch"], base_sha)
        with self._lock:
            task.update({"worktree": str(worktree), "base_branch": base_branch,
                         "base_sha": base_sha, "engine": engine.name})
        self._set_state(task, "running", f"engine={engine.name} base={base_branch}@{base_sha[:8]}")
        self._notify(task, (
            f"🔨 <b>Forge al lavoro</b> <code>{task['id'][:6]}</code> ({engine.name})\n"
            f"{_esc(task['request'][:400])}"))

        def test_runner(paths: list[str] | None):
            changed = git_ops.git(worktree, "status", "--porcelain").splitlines()
            files = [line[3:] for line in changed]
            return run_test_command(worktree, self.cfg.test_cmd,
                                    paths or self._test_paths(worktree, files, task["services"]))

        prompt = build_task_prompt(task["request"], task["services"], task.get("context", ""))
        t0 = time.perf_counter()
        result = engine.run(worktree, prompt, test_runner)
        with self._lock:
            task.update({"summary": result.summary, "engine_log_tail": result.log_tail,
                         "turns": result.turns, "cost_usd": result.cost_usd,
                         "engine_ms": int((time.perf_counter() - t0) * 1000)})

        sha = git_ops.commit_all(
            worktree, f"forge({task['id']}): {task['request'][:60]}\n\n{result.summary[:1500]}",
            self.cfg.git_author_name, self.cfg.git_author_email)
        if not sha:
            self._cleanup(task, delete_branch=True)
            task["error"] = None if result.ok else result.summary[:500]
            self._set_state(task, "no_changes", "engine produced no diff")
            self._notify(task, (
                f"⚠️ Forge <code>{task['id'][:6]}</code>: nessuna modifica prodotta.\n"
                f"{_esc(result.summary[:500])}"))
            return

        changed = git_ops.changed_files(worktree, base_sha)
        tests_ok, tests_out = run_test_command(
            worktree, self.cfg.test_cmd, self._test_paths(worktree, changed, task["services"]))
        with self._lock:
            task.update({
                "commit_sha": sha,
                "changed_files": changed,
                "touched_services": services_from_paths(changed),
                "diff_stat": git_ops.diff_stat(worktree, base_sha),
                "tests": {"ok": tests_ok, "output_tail": tests_out[-3000:]},
            })
        if self.cfg.push_branch:
            try:
                git_ops.push(worktree, task["branch"])
            except Exception as exc:
                logger.warning("[🔄] event=forge_push_failed task_id=%s error=%s", task["id"], exc)

        self._set_state(task, "awaiting_review", f"engine_ok={result.ok} tests_ok={tests_ok}")
        tests_label = {True: "✅ test ok", False: "❌ test falliti", None: "➖ nessun test"}[tests_ok]
        short = task["id"][:6]
        self._notify(task, (
            f"🧩 <b>Forge: modifica pronta</b> <code>{short}</code> · {tests_label}\n"
            f"{_esc(result.summary[:900])}\n\n<pre>{_esc(task['diff_stat'][-900:])}</pre>\n"
            f"Rispondi \"approva sviluppo {short}\" per applicarla, \"rifiuta {short}\" per scartarla."))

        if task.get("auto_merge") and tests_ok is True and result.ok:
            with self._lock:
                task["approved_by"] = "policy:auto_merge"
            self._set_state(task, "approved", "auto_merge policy")
            self._merge_and_deploy(task, "policy:auto_merge")

    def _check_mergeable(self, task: dict) -> None:
        repo = self.cfg.repo_path
        base_branch = task.get("base_branch") or self._base_branch()
        current = git_ops.current_branch(repo)
        if current != base_branch:
            raise ForgeError(f"Repo is on '{current}', expected '{base_branch}': switch branch first", 409)
        if not git_ops.is_clean(repo):
            raise ForgeError("Repo has uncommitted changes: commit or stash them, then approve again", 409)

    def _merge_and_deploy(self, task: dict, approved_by: str) -> None:
        repo = self.cfg.repo_path
        try:
            self._check_mergeable(task)
        except ForgeError as exc:
            task["error"] = str(exc)
            self._set_state(task, "awaiting_review", f"not mergeable: {exc}")
            self._notify(task, f"⚠️ Forge <code>{task['id'][:6]}</code>: merge impossibile — {_esc(str(exc))}")
            return
        self._set_state(task, "merging", f"approved by {approved_by}")
        try:
            merge_sha = git_ops.merge_no_ff(
                repo, task["branch"], f"forge: merge {task['branch']} — {task['request'][:60]}",
                self.cfg.git_author_name, self.cfg.git_author_email)
        except git_ops.GitError as exc:
            task["error"] = str(exc)[:1000]
            self._set_state(task, "awaiting_review", f"merge failed: {exc}")
            self._notify(task, f"⚠️ Forge <code>{task['id'][:6]}</code>: merge fallito (conflitto?) — {_esc(str(exc)[:300])}")
            return
        with self._lock:
            task["merge_sha"] = merge_sha
        self._cleanup(task, delete_branch=False)
        self._set_state(task, "merged", f"merge {merge_sha[:8]}")

        services = task.get("touched_services") or []
        if not self.cfg.deploy_cmd or not services:
            self._notify(task, (
                f"✅ <b>Forge: applicata</b> <code>{task['id'][:6]}</code> (merge {merge_sha[:8]}).\n"
                + ("Riavvia i servizi per attivarla." if services else "")))
            return

        ok, out = self._deploy(services)
        task["deploy"] = {"ok": ok, "output_tail": out[-2000:]}
        unhealthy = self._unhealthy(services) if ok else services
        if ok and not unhealthy:
            self._set_state(task, "deployed", f"services={','.join(services)}")
            self._notify(task, (
                f"🚀 <b>Forge: in produzione</b> <code>{task['id'][:6]}</code> → {', '.join(services)} ok.\n"
                f"Rollback: \"rollback sviluppo {task['id'][:6]}\"."))
            return
        why = f"deploy_ok={ok} unhealthy={unhealthy}"
        if self.cfg.auto_rollback:
            self._do_rollback(task, f"auto: {why}")
        else:
            self._notify(task, f"⚠️ Forge <code>{task['id'][:6]}</code>: deploy problematico ({_esc(why)}).")

    def _do_rollback(self, task: dict, note: str) -> None:
        revert_sha = git_ops.revert_merge(self.cfg.repo_path, task["merge_sha"],
                                          self.cfg.git_author_name, self.cfg.git_author_email)
        with self._lock:
            task["revert_sha"] = revert_sha
        services = task.get("touched_services") or []
        if self.cfg.deploy_cmd and services:
            self._deploy(services)
        self._set_state(task, "rolled_back", f"revert {revert_sha[:8]} {note}")
        self._notify(task, f"↩️ <b>Forge: rollback</b> <code>{task['id'][:6]}</code> ({_esc(note[:200])}).")

    def _deploy(self, services: list[str]) -> tuple[bool, str]:
        cmd = self.cfg.deploy_cmd.replace("{services}", " ".join(services))
        try:
            proc = subprocess.run(cmd, shell=True, cwd=str(self.cfg.repo_path),
                                  capture_output=True, text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            return False, "deploy timed out"
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    def _unhealthy(self, services: list[str]) -> list[str]:
        wait_seconds(self.cfg.verify_delay_seconds)
        bad = []
        for name in services:
            try:
                resp = requests.post(f"{self.cfg.hub_api_url}/route/{name}/health",
                                     json={"method": "GET", "headers": {}, "query": {}, "body": None,
                                           "timeout_seconds": 8}, timeout=10)
                status = int((resp.json() or {}).get("status_code", 500)) if resp.ok else resp.status_code
                if status >= 400:
                    bad.append(name)
            except Exception:
                bad.append(name)
        return bad

    def _cleanup(self, task: dict, delete_branch: bool) -> None:
        worktree = Path(task.get("worktree") or self.cfg.worktrees_path / task["id"])
        try:
            git_ops.remove_worktree(self.cfg.repo_path, worktree, task.get("branch"), delete_branch)
        except Exception as exc:
            logger.warning("[🔄] event=forge_cleanup_failed task_id=%s error=%s", task["id"], exc)

    def _notify(self, task: dict, text: str) -> None:
        """Hermes direct send to the requester + system event for subscriptions."""
        hub = self.cfg.hub_api_url
        target = task.get("notify_target") or self.cfg.notify_target

        def _route(path: str, body: dict) -> None:
            requests.post(f"{hub}/route/hermes/{path}",
                          json={"method": "POST", "headers": {}, "query": {}, "body": body,
                                "timeout_seconds": 8}, timeout=10)

        try:
            if target:
                _route("api/dispatch/send", {"channel": "telegram", "target": str(target), "message": text})
            _route("api/events/ingest", {
                "domain": "system", "event_type": "hephaestus.forge", "entity_id": task["id"],
                "payload": {"_message": text, "task_id": task["id"], "state": task.get("state")}})
        except Exception as exc:
            logger.warning("[🔄] event=forge_notify_failed task_id=%s error=%s", task["id"], exc)


def _esc(text: str) -> str:
    import html
    return html.escape(str(text or ""))

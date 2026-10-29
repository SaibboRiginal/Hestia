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
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from . import git_ops
from . import deployer
from .agenda_client import KEY_FINAL, KEY_NIGHTS, AgendaClient
from .claude_budget import ClaudeBudget, ClaudeBudgetState, ClaudeSchedule
from .agent_tools import run_test_command
from .config import ENGINE_GROUP, ForgeConfig, engine_group, normalize_engine
from ..core.shared_imports import import_shared_symbol

PresenceClient = import_shared_symbol("hestia_common.presence_client", "PresenceClient")
from .engines import build_engines, select_engine, wait_seconds
from . import forge_settings
from .prompts import build_task_prompt, workdoc_name
from . import review as forge_review
from .transcript import TaskArtifacts

logger = logging.getLogger("hestia_hephaestus.forge")

ACTIVE_STATES = {"queued", "running", "reviewing", "approved", "merging"}  # "scheduled" = waiting for Claude window
TERMINAL_STATES = {"failed", "rejected", "rolled_back", "deployed", "merged", "no_changes"}


# Permission modes (like Claude Code / Codex), one per group:
#   ask       → Athena/Argus tasks wait for "approva sviluppo <id>" before coding;
#               merge waits for you.  User-typed tasks start (you asked), merge waits.
#   auto      → every task codes on its own branch; merge waits for you.
#   full_auto → codes and, if engine ok + tests green, merges/deploys alone
#               (health check + automatic rollback).
# Groups: "local" (oracle engine on a chain with no billed step) and "cloud" (billed steps or Claude Code).
# Default engine and modes are central settings (forge_settings → Themis), applied live.
MODES = ("ask", "auto", "full_auto")
_MODE_ALIASES = {"propose": "ask", "auto_start": "auto", "yolo": "full_auto", "full": "full_auto"}
DEFAULT_MODES = {"local": "auto", "cloud": "ask"}
USER_SOURCES = {"user", "telegram", "ui", "oracle"}
# A fix made elsewhere (external AI via MCP, forge_submit_branch): Forge fetches, tests, asks as usual.
BRANCH_SUBMIT_STATES = {"proposed", "scheduled", "failed", "no_changes", "awaiting_review"}
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


def normalize_mode(mode: str) -> str:
    mode = str(mode or "").strip().lower().replace("-", "_")
    return _MODE_ALIASES.get(mode, mode)


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
        self._default_engine = "oracle"
        self._modes = dict(DEFAULT_MODES)
        self._apply_settings(forge_settings.settings.values())
        forge_settings.settings.on_change(self._apply_settings)
        self.claude_budget = ClaudeBudget(ClaudeSchedule())
        self.agenda = AgendaClient(cfg.hub_api_url)
        # Assistant presence (Chronos): autonomous work waits for the right state; tasks and
        # deploys are reported as activities ("Occupato: Forge", "Sto mangiando").
        self.presence = PresenceClient("hephaestus", cfg.hub_api_url)
        # Sviluppo page: transcript, full test output, engine/deploy logs per task.
        self.artifacts = TaskArtifacts(cfg.state_file.parent / "tasks", cfg.worktrees_path)
        self._agenda_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forge-agenda")
        # Automatic review + team plan (Cindy 3 + 31): a fresh model with no tools, through Oracle.
        self.reviewer = forge_review.ForgeReviewer(cfg.hub_api_url)
        self._load()
        self._load_settings()

    def _register_agenda_templates(self) -> None:
        """Calendar wizard: the user can schedule a development task (fires POST /forge/tasks)."""
        try:
            from ..core.shared_imports import import_shared_symbol
            template = import_shared_symbol("hestia_common.agenda_client", "template")
            self.agenda.register_async([], templates=[template(
                "develop", "Sviluppo programmato", service="hephaestus", path="/api/hephaestus/forge/tasks",
                type="task", types=["task"], icon="terminal",
                fields={"request": {"type": "string", "label": "Richiesta", "format": "textarea", "description": "Cosa sviluppare o correggere"},
                        "engine": {"type": "string", "label": "Motore", "enum": ["", "oracle", "claude"], "default": "",
                                   "description": "Motore (vuoto = predefinito)"}},
                required=["request"], body={"source": "agenda", "requested_by": "user"},
                title="Forge: sviluppo programmato", timeout_seconds=30,
                description="All'orario scelto Forge avvia il task di sviluppo (diff da approvare come sempre).")])
        except Exception as exc:  # never block Forge start on the agenda
            logger.warning("[🔄] event=forge_agenda_templates_failed error=%s", exc)

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
                sched = data.get("claude_schedule")
                state = data.get("claude_state")
                if isinstance(sched, dict) or isinstance(state, dict):
                    self.claude_budget = ClaudeBudget(
                        ClaudeSchedule(**{k: v for k, v in (sched or {}).items()
                                          if k in ClaudeSchedule.__dataclass_fields__}),
                        ClaudeBudgetState(**{k: v for k, v in (state or {}).items()
                                             if k in ClaudeBudgetState.__dataclass_fields__}))
        except Exception as exc:
            logger.warning("[🔄] event=forge_settings_load_failed error=%s", exc)

    def _apply_settings(self, values: dict[str, Any]) -> None:
        """Live settings from Themis (initial load and every change)."""
        engine = normalize_engine(values.get(forge_settings.ENGINE, ""))
        if engine in self.engines and engine != self._default_engine:
            self._default_engine = engine
            logger.info("event=forge_default_engine_applied engine=%s", engine)
        if forge_settings.PAUSED in values:
            logger.info("event=forge_pause_applied paused=%s", values.get(forge_settings.PAUSED))
        for group, key in forge_settings.MODE.items():
            mode = normalize_mode(values.get(key, ""))
            if mode in MODES and self._modes.get(group) != mode:
                self._modes[group] = mode
                logger.info("event=forge_mode_applied group=%s mode=%s", group, mode)

    @property
    def default_engine(self) -> str:
        return self._default_engine

    @property
    def paused(self) -> bool:
        """Manual brake (Themis ``hephaestus.forge.paused``): nothing starts on its own."""
        return forge_settings.get_bool(forge_settings.PAUSED)

    def set_paused(self, paused: bool, by: str = "user") -> dict[str, Any]:
        """User switch (Sviluppo page, Telegram): persisted as a central setting. Resuming
        restarts nothing: tasks held during the pause stay proposed until the user starts them."""
        saved = forge_settings.settings.put(forge_settings.PAUSED, bool(paused), actor="user",
                                            reason=f"Sviluppo {'in pausa' if paused else 'ripreso'} da {by}")
        if not saved:
            raise ForgeError("Themis non ha salvato l'impostazione: riprova tra poco", 503)
        # Apply now (Themis also pushes it back): no autonomous start slips in meanwhile.
        forge_settings.settings.apply({**forge_settings.settings._stored, forge_settings.PAUSED: bool(paused)})
        with self._lock:
            held = [t["id"] for t in self._tasks.values()
                    if t.get("held_by_pause") and t.get("state") == "proposed"]
        logger.info("event=forge_pause_set paused=%s by=%s held=%d", bool(paused), by, len(held))
        return {"paused": self.paused, "held": held}

    def _autonomous(self, task: dict) -> bool:
        """Started by a module (Athena, Argus, remediation, Claude windows), not by the user."""
        return task.get("source") not in USER_SOURCES and not task.get("manual_start")

    _WORD = re.compile(r"[a-zà-ù0-9]{3,}")

    @classmethod
    def _words(cls, text: str) -> set[str]:
        return set(cls._WORD.findall(str(text or "").lower()))

    def find_duplicate(self, request: str, source: str, services: list[str] | None = None,
                       context: str = "") -> dict[str, Any] | None:
        """A module's proposal equal or very similar to a task of the last ``hephaestus.forge.dedup_days``
        days, in any state (rejected too: no re-proposing). Similar = same services and word overlap
        ≥ 60% on request + start of context (templated Argus/remediation requests differ only there)."""
        days = forge_settings.get_int(forge_settings.DEDUP_DAYS, 0)
        services = sorted(str(x).strip().lower() for x in (services or []) if str(x).strip())
        words = self._words(f"{request} {str(context or '')[:600]}")
        if days <= 0 or source in USER_SOURCES or not words:
            return None
        since = datetime.now(timezone.utc).timestamp() - days * 86400
        with self._lock:
            tasks = list(self._tasks.values())
        for task in sorted(tasks, key=lambda t: t.get("created_at", ""), reverse=True):
            try:
                created = datetime.fromisoformat(str(task.get("created_at"))).timestamp()
            except ValueError:
                continue
            if created < since:
                continue
            if sorted(task.get("services") or []) != services:
                continue
            other = self._words(f"{task.get('request', '')} {str(task.get('context') or '')[:600]}")
            if other and len(words & other) / len(words | other) >= 0.6:
                return task
        return None

    def _hold(self, task: dict, note: str) -> None:
        """Pause: keep the task as a silent proposal (no notification), the user starts it by hand."""
        with self._lock:
            task["held_by_pause"] = True
        self._set_state(task, "proposed", f"sviluppo in pausa: {note}")
        logger.info("event=forge_task_held_by_pause task_id=%s source=%s", task["id"], task.get("source"))

    def set_default_engine(self, engine: str) -> dict[str, Any]:
        """User switch of the default engine: applied now, persisted as a central setting."""
        name = normalize_engine(engine)
        if name not in self.engines:
            raise ForgeError(f"Unknown engine '{engine}'. Use: {', '.join(self.engines)}")
        ok, reason = self.engines[name].available()
        self._default_engine = name
        saved = forge_settings.settings.put(forge_settings.ENGINE, name, actor="user")
        logger.info("event=forge_default_engine_set engine=%s available=%s saved=%s", name, ok, saved)
        return {"default_engine": name, "available": ok, "detail": reason, "saved": saved}

    def settings(self) -> dict[str, Any]:
        return {"default_engine": self._default_engine, "fallback": forge_settings.fallback(),
                "modes": dict(self._modes), "engine_groups": ENGINE_GROUP,
                "claude_budget": self.claude_budget.status()}

    def set_claude_schedule(self, **changes: Any) -> dict[str, Any]:
        """Update the Claude Pro budget window (reset day/time, window, night, caps)."""
        from dataclasses import asdict, replace
        clean = {k: v for k, v in changes.items()
                 if k in ClaudeSchedule.__dataclass_fields__ and v not in (None, "")}
        try:
            schedule = replace(self.claude_budget.schedule, **clean).validate()
        except (TypeError, ValueError) as exc:
            raise ForgeError(f"Invalid Claude schedule: {exc}")
        self.claude_budget = ClaudeBudget(schedule, self.claude_budget.state)
        self._save_settings()
        self.agenda.register_claude_windows(schedule, force=True)
        logger.info("event=forge_claude_schedule_set schedule=%s", asdict(schedule))
        return self.claude_budget.status()

    def set_mode(self, mode: str, group: str = "") -> dict[str, Any]:
        """Set permission mode for a group (local|cloud), or both when group is empty."""
        mode = normalize_mode(mode)
        if mode not in MODES:
            raise ForgeError(f"Unknown mode '{mode}'. Use: {' | '.join(MODES)}")
        group = str(group or "").strip().lower()
        group = ENGINE_GROUP.get(normalize_engine(group), group)
        targets = [group] if group else list(DEFAULT_MODES)
        for g in targets:
            if g not in DEFAULT_MODES:
                raise ForgeError(f"Unknown group '{g}'. Use: local | cloud")
            self._modes[g] = mode
            forge_settings.settings.put(forge_settings.MODE[g], mode, actor="user")
        logger.info("event=forge_mode_set groups=%s mode=%s", targets, mode)
        return self.settings()

    def _save_settings(self) -> None:
        try:
            self.cfg.settings_file.parent.mkdir(parents=True, exist_ok=True)
            from dataclasses import asdict
            self.cfg.settings_file.write_text(json.dumps({
                "claude_schedule": asdict(self.claude_budget.schedule),
                "claude_state": asdict(self.claude_budget.state)}), encoding="utf-8")
        except Exception as exc:
            logger.warning("[🔄] event=forge_settings_save_failed error=%s", exc)

    def _engine_name_for(self, engine_requested: str) -> str:
        engine, _ = select_engine(self.engines, engine_requested, self._default_engine, forge_settings.fallback())
        return engine.name if engine else normalize_engine(engine_requested) or self._default_engine

    def _mode_for(self, engine_requested: str) -> tuple[str, str]:
        name = self._engine_name_for(engine_requested)
        group = engine_group(self.engines.get(name) or name)
        return self._modes.get(group, "ask"), group

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
        # Serial executor: mirror updates must land in state order.
        self._agenda_pool.submit(self._mirror_agenda, dict(task))

    # ── assistant agenda mirror ─────────────────────────────────────────────
    _AGENDA_LABELS = {
        "proposed": "⏳ da approvare",
        "queued": "🔨 in coda",
        "running": "🔨 in lavorazione",
        "reviewing": "🔎 revisione automatica",
        "awaiting_review": "👀 diff da rivedere",
        "waiting_limit": "⏸ attende il limite di Claude",
        "approved": "🔀 merge in corso",
        "merging": "🔀 merge in corso",
    }

    def _mirror_agenda(self, task: dict) -> None:
        """Every Forge task is visible in Hestia's agenda (key forge.task.<id>).

        ``scheduled`` → event at the next Claude window (the user can move it:
        the scheduler waits; cancel it: the task is rejected). Terminal states
        complete the entry so the agenda keeps only live work."""
        state = task.get("state")
        try:
            if state in {"failed", "rolled_back"}:
                last = (task.get("history") or [{}])[-1]
                self.agenda.fail_task(task["id"], f"Forge {state}: {str(last.get('note') or '')[:200]}")
                return
            if state in TERMINAL_STATES:
                self.agenda.hide_task(task["id"])
                return
            if state == "scheduled":
                return  # handled by _schedule (needs the window time)
            label = self._AGENDA_LABELS.get(state)
            if label:
                self.agenda.show_task(task["id"], f"{label}: {task.get('request', '')}", _now(),
                                      f"Task Forge {task['id']} ({state}). Engine: "
                                      f"{task.get('engine_requested') or self._default_engine}.",
                                      parent=task.get("agenda_parent"))
        except Exception as exc:
            logger.debug("event=forge_agenda_mirror_failed task_id=%s error=%s", task.get("id"), exc)

    def _agenda_gate(self, task: dict) -> tuple[bool, str]:
        """Scheduled task vs its agenda entry: cancelled → reject; moved later → wait."""
        reachable, item = self.agenda.lookup(self.agenda.task_key(task["id"]))
        if not reachable or not item:
            return True, ""
        if item.get("status") == "cancelled":
            self.reject(task["id"], reason="annullato dall'agenda di Hestia", rejected_by="user")
            return False, "cancelled in agenda"
        try:
            start = datetime.fromisoformat(str(item.get("start_at")).replace("Z", "+00:00"))
            if item.get("user_modified") and start > datetime.now(timezone.utc):
                return False, f"moved in agenda to {start.isoformat()[:16]}"
        except (TypeError, ValueError):
            pass
        return True, ""

    # ── lifecycle ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._register_agenda_templates()
        # Resilience: resume anything interrupted by a restart.
        with self._lock:
            for task in self._tasks.values():
                if task.get("state") in {"queued", "running", "reviewing"}:
                    task["state"] = "queued"
                    self._queue.put(task["id"])
                elif task.get("state") in {"approved", "merging"} and not task.get("merge_sha"):
                    task["state"] = "approved"
                    self._queue.put(task["id"])
        self._worker = threading.Thread(target=self._work_loop, daemon=True, name="forge-worker")
        self._worker.start()
        threading.Thread(target=self._scheduler_loop, daemon=True, name="forge-scheduler").start()
        threading.Thread(target=self.agenda.register_claude_windows, args=(self.claude_budget.schedule,),
                         daemon=True, name="forge-agenda-register").start()
        logger.info("event=forge_started repo=%s default_engine=%s", self.cfg.repo_path, self._default_engine)

    def _work_loop(self) -> None:
        while True:
            task_id = self._queue.get()
            task = self.get(task_id)
            if not task or task.get("state") not in {"queued", "approved"}:
                continue
            try:
                if task["state"] == "queued" and self.paused and self._autonomous(task):
                    self._hold(task, "in coda")
                    continue
                if task["state"] == "approved":
                    with self.presence.activity("hephaestus.deploy", label="aggiornamento", load="heavy",
                                                kind="maintenance", ttl_seconds=1800):
                        self._merge_and_deploy(task, task.get("approved_by", "user"))
                elif (task.get("external") or {}).get("pending"):
                    with self.presence.activity("forge.task", label="Forge", load="medium", ttl_seconds=3600):
                        self._run_external(task)
                else:
                    engine = self._engine_name_for(task.get("engine_requested", "auto"))
                    with self.presence.activity("forge.task", label="Forge", load="heavy",
                                                resource="claude_quota" if engine == "claude" else "gpu",
                                                ttl_seconds=6 * 3600):
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
            "paused": self.paused,
            "repo_path": str(self.cfg.repo_path),
            "repo_ok": repo_ok,
            "base_branch": self._base_branch() if repo_ok else None,
            "engine_default": self._default_engine,
            "engine_fallback": forge_settings.fallback(),
            "engines": engines,
            "auto_merge": forge_settings.get_bool(forge_settings.AUTO_MERGE),
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
               source: str = "user", requested_by: str = "user", auto_start: bool | None = None,
               auto_merge: bool | None = None, context: str = "", notify_target: str = "",
               workdoc: str = "", parent_task: str = "", agenda_parent: str = "") -> dict[str, Any]:
        """``workdoc``: continue an existing docs/work/<workdoc>/ (SPEC/PROGRESS/CHANGELOG).
        ``parent_task``: follow-up of an earlier task (Sviluppo page "Chiedi una modifica")."""
        if not self.cfg.enabled:
            raise ForgeError("Forge disabled (HEPHAESTUS_FORGE_ENABLED=0)", 503)
        if not git_ops.is_repo(self.cfg.repo_path):
            raise ForgeError(f"Repo not mounted at {self.cfg.repo_path} (volume ./:/repo)", 503)
        request = str(request or "").strip()
        if len(request) < 8:
            raise ForgeError("Request too short: describe what to build or fix")
        parent = self.get(parent_task) if parent_task else None
        if parent_task and not parent:
            raise ForgeError(f"Parent task '{parent_task}' not found", 404)
        if parent:  # follow-up: same dossier and services, the engine knows what was done before
            workdoc = workdoc or parent.get("workdoc") or ""
            services = services or parent.get("services") or []
            context = (f"Segue il task Forge {parent['id']} ({parent.get('state')}): "
                       f"{str(parent.get('request') or '')[:600]}\nEsito: {str(parent.get('summary') or '')[:1200]}\n"
                       + str(context or ""))
        duplicate = self.find_duplicate(request, source, services, context)
        if duplicate:
            logger.info("event=forge_duplicate_skipped source=%s duplicate_of=%s state=%s",
                        source, duplicate["id"], duplicate.get("state"))
            return {**duplicate, "duplicate": True}
        task_id = uuid.uuid4().hex[:12]
        task = {
            "id": task_id,
            "request": request[:4000],
            "services": [s.strip().lower() for s in (services or []) if str(s).strip()],
            "engine_requested": normalize_engine(engine) or "auto",
            "source": source,
            "requested_by": requested_by,
            "context": str(context or "")[:4000],
            "workdoc": re.sub(r"[^A-Za-z0-9._-]", "", str(workdoc or ""))[:120],
            "parent_task": parent["id"] if parent else None,
            "agenda_parent": re.sub(r"[^A-Za-z0-9._:-]", "", str(agenda_parent or ""))[:160] or None,
            "auto_merge": forge_settings.get_bool(forge_settings.AUTO_MERGE) if auto_merge is None else bool(auto_merge),
            "notify_target": notify_target or self.cfg.notify_target,
            "branch": f"auto/forge/{task_id}",
            "created_at": _now(),
            "updated_at": _now(),
            "state": "new",
            "history": [],
        }
        mode, group = self._mode_for(task["engine_requested"])
        why = f"mode[{group}]={mode}"
        if auto_start is None:
            auto_start = source in USER_SOURCES or mode in {"auto", "full_auto"}
        if auto_merge is None and mode == "full_auto":
            task["auto_merge"] = True
        task["start_policy"] = why
        # Claude Pro budget: autonomous claude work waits for the pre-reset nights.
        task["budgeted"] = source not in USER_SOURCES and self._engine_name_for(task["engine_requested"]) == "claude"
        with self._lock:
            self._tasks[task_id] = task
        if self.paused and self._autonomous(task):
            self._hold(task, f"proposto da {source} ({why})")
        elif auto_start and task["budgeted"]:
            self._schedule(task, f"submitted by {source}")
        elif auto_start:
            self._enqueue(task, f"submitted by {requested_by} ({source})")
        else:
            self._set_state(task, "proposed", f"proposed by {source} ({why})")
            self._notify(task, (
                f"💡 <b>Proposta di sviluppo</b> <code>{task_id[:6]}</code>\n{_esc(request[:600])}\n\n"
                f"Rispondi \"approva sviluppo {task_id[:6]}\" per avviarla, \"rifiuta {task_id[:6]}\" per scartarla."))
        return task

    def approve(self, task_id: str, approved_by: str = "user", now: bool = False,
                engine: str = "") -> dict[str, Any]:
        """``engine``: the user picks who develops this task when starting it (local | cloud | claude);
        an explicit choice starts now, outside the Claude budget windows."""
        task = self._require(task_id)
        state = task.get("state")
        if state in {"proposed", "scheduled"}:
            chosen = normalize_engine(engine) if engine else ""
            if engine and chosen not in self.engines:
                raise ForgeError(f"Unknown engine '{engine}'. Use: {', '.join(self.engines)}")
            with self._lock:   # the user's own start: the pause no longer holds it
                task["manual_start"] = True
                task.pop("held_by_pause", None)
                if chosen:
                    task["engine_requested"] = chosen
                    task["budgeted"] = False
            if task.get("budgeted") and not now:
                self._schedule(task, f"approved by {approved_by}, waits for Claude budget window")
            else:
                self._enqueue(task, f"start approved by {approved_by}{' (now)' if now else ''}")
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
        if task.get("state") not in {"proposed", "scheduled", "waiting_limit", "awaiting_review", "failed",
                                     "no_changes"}:
            raise ForgeError(f"Task in state '{task.get('state')}' cannot be rejected")
        self._cleanup(task, delete_branch=True)
        self.agenda.hide_task(task["id"])
        self._set_state(task, "rejected", f"by {rejected_by}: {reason}")
        return task

    def rollback(self, task_id: str, reason: str = "", requested_by: str = "user") -> dict[str, Any]:
        task = self._require(task_id)
        if task.get("state") not in {"merged", "deployed"} or not task.get("merge_sha"):
            raise ForgeError(f"Task in state '{task.get('state')}' has nothing to roll back")
        self._do_rollback(task, f"by {requested_by}: {reason}")
        return task

    def retry(self, task_id: str, requested_by: str = "user") -> dict[str, Any]:
        """Same request again as a new task (failed / no changes / rejected / rolled back)."""
        old = self._require(task_id)
        if old.get("state") in ACTIVE_STATES or old.get("state") in {"proposed", "scheduled", "awaiting_review",
                                                                        "waiting_limit", "reviewing"}:
            raise ForgeError(f"Task in state '{old.get('state')}' is still open: nothing to retry", 409)
        return self.submit(request=old.get("request", ""), services=old.get("services") or [],
                           engine="" if old.get("engine_requested") in (None, "auto") else old["engine_requested"],
                           source="ui", requested_by=requested_by, context=f"Riprova del task {old['id']}. "
                           f"Esito precedente: {str(old.get('error') or old.get('summary') or '')[:800]}"
                           + notes_text(old),
                           workdoc=old.get("workdoc") or "")

    def add_note(self, task_id: str, text: str, by: str = "user") -> dict[str, Any]:
        """An analysis or hint on a task (Sviluppo page, external AI): shown with the task, given to the engine
        when the task runs or is retried."""
        task = self._require(task_id)
        text = str(text or "").strip()
        if len(text) < 3:
            raise ForgeError("Note too short")
        note = {"ts": _now(), "by": str(by or "user")[:80], "text": text[:4000]}
        with self._lock:
            notes = task.setdefault("notes", [])
            notes.append(note)
            del notes[:-30]
            task["updated_at"] = note["ts"]
        self._save()
        logger.info("event=forge_task_note task_id=%s by=%s chars=%d", task["id"], note["by"], len(note["text"]))
        return task

    def submit_branch(self, task_id: str, branch: str, summary: str = "", by: str = "user") -> dict[str, Any]:
        """"I fixed it on this branch": Forge fetches ``branch`` from origin, runs its tests and asks for the
        approval as usual (never merges on its own). The external AI codes wherever it likes; Forge stays the
        only deploy gate."""
        task = self._require(task_id)
        branch = str(branch or "").strip()
        if (not _BRANCH_RE.match(branch) or ".." in branch or "//" in branch or branch.endswith((".lock", "/"))
                or branch.startswith("auto/forge/")):
            raise ForgeError(f"Invalid branch '{branch}' (a branch on origin, not auto/forge/*)")
        state = task.get("state")
        if state not in BRANCH_SUBMIT_STATES:
            raise ForgeError(f"Task in state '{state}': a branch can be submitted when it is "
                             f"{', '.join(sorted(BRANCH_SUBMIT_STATES))}", 409)
        if not git_ops.is_repo(self.cfg.repo_path):
            raise ForgeError(f"Repo not mounted at {self.cfg.repo_path} (volume ./:/repo)", 503)
        with self._lock:
            task["external"] = {"branch": branch, "summary": str(summary or "").strip()[:4000],
                                "by": str(by or "user")[:80], "at": _now(), "pending": True}
            task["manual_start"] = True        # a deliberate submission, not an autonomous proposal
            task.pop("held_by_pause", None)
            task["auto_merge"] = False         # the owner approves every external fix
            task["error"] = None
        if state == "scheduled":
            self.agenda.hide_task(task["id"])
        self._enqueue(task, f"branch {branch} submitted by {by}")
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

    def _schedule(self, task: dict, note: str) -> None:
        st = self.claude_budget.status()
        self._set_state(task, "scheduled", f"{note}; {st['reason']}")
        nights = self.agenda.window(KEY_NIGHTS) or {}
        self.agenda.show_task(task["id"], task["request"], nights.get("next_open") or st["next_reset"],
                              f"Task Forge programmato (Claude Pro). id={task['id']}",
                              parent=task.get("agenda_parent"))
        self._notify(task, (
            f"🌙 <b>Sviluppo programmato</b> <code>{task['id'][:6]}</code> (Claude Pro)\n"
            f"{_esc(task['request'][:300])}\n"
            f"Parte nella finestra notturna prima del reset ({_esc(st['next_reset'][:16])}). "
            f"Per avviarlo ora: \"approva sviluppo {task['id'][:6]} subito\"."))

    def claude_window(self) -> tuple[bool, str]:
        """Agenda windows first (user can move/skip them), built-in schedule as fallback."""
        st = self.claude_budget.status()
        if st["phase"] == "exhausted":
            return False, st["reason"]
        final, nights = self.agenda.window(KEY_FINAL), self.agenda.window(KEY_NIGHTS)
        if final is not None and nights is not None and (final.get("exists") or nights.get("exists")):
            if final.get("active"):
                return True, "agenda: ultime ore prima del reset"
            if nights.get("active"):
                cap = int((nights.get("params") or {}).get("night_max_tasks",
                                                           self.claude_budget.schedule.night_max_tasks))
                if st["used_tonight"] < cap:
                    return True, "agenda: finestra notturna"
                return False, f"agenda: tetto notturno raggiunto ({st['used_tonight']}/{cap})"
            skipped = nights.get("skipped_now") or final.get("skipped_now")
            return False, "agenda: finestra saltata dall'utente" if skipped else "agenda: finestra chiusa"
        return self.claude_budget.can_start()

    def presence_allows_autonomous(self) -> tuple[bool, str]:
        """Autonomous Claude work also needs the assistant presence: effects ``work.heavy`` and
        ``llm.claude`` = allow (e.g. "Sonno profondo"; not while the user is "Sveglio" or it is
        "Stanco"). Presence unknown (Chronos down) → the budget windows alone decide."""
        state = self.presence.get()
        if not state:
            return True, "presence unknown: budget windows decide"
        effects = state.get("effects") or {}
        heavy, claude = effects.get("work.heavy", "allow"), effects.get("llm.claude", "allow")
        if heavy != "allow" or claude != "allow":
            return False, f"presence {state.get('base')}: work.heavy={heavy} llm.claude={claude}"
        return True, f"presence {state.get('base')}"

    def _reap_unlinked(self) -> None:
        """Proposed tasks linked to an agenda item: the user cancelled it (or its parent) → reject."""
        with self._lock:
            linked = [t for t in self._tasks.values() if t.get("state") == "proposed" and t.get("agenda_parent")]
        for task in linked:
            reachable, item = self.agenda.lookup(self.agenda.task_key(task["id"]))
            if reachable and item and item.get("status") == "cancelled":
                try:
                    self.reject(task["id"], reason="annullato dall'agenda di Hestia (voce collegata)",
                                rejected_by="user")
                except ForgeError as exc:
                    logger.debug("event=forge_reap_unlinked_skip task_id=%s error=%s", task["id"], exc)

    def _scheduler_loop(self) -> None:
        """Start one budgeted claude task at a time when the window allows."""
        while True:
            time.sleep(forge_settings.get_int(forge_settings.SCHEDULER_INTERVAL, 30))
            try:
                self._reap_unlinked()
                with self._lock:
                    busy = any(t.get("state") in ACTIVE_STATES for t in self._tasks.values())
                    waiting = sorted((t for t in self._tasks.values() if t.get("state") == "scheduled"
                                      and not (self.paused and self._autonomous(t))),
                                     key=lambda t: t["created_at"])
                if busy or not waiting:
                    continue
                ok, reason = self.claude_window()
                if not ok:
                    logger.debug("event=forge_claude_window_closed reason=%s waiting=%d", reason, len(waiting))
                    continue
                ok, why = self.presence_allows_autonomous()
                if not ok:
                    logger.debug("event=forge_held_by_presence reason=%s waiting=%d", why, len(waiting))
                    continue
                candidate = None
                for task in waiting:
                    allowed, why = self._agenda_gate(task)
                    if allowed:
                        candidate = task
                        break
                    logger.debug("event=forge_task_held_by_agenda task_id=%s reason=%s", task["id"], why)
                if candidate is None:
                    continue
                self.claude_budget.record_start()
                self._save_settings()
                self._enqueue(candidate, f"Claude budget window: {reason}")
            except Exception as exc:
                logger.warning("[🔄] event=forge_scheduler_error error=%s", exc)

    @staticmethod
    def _seconds_until(iso: str) -> float:
        try:
            end = datetime.fromisoformat(str(iso))
            end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            return max(60.0, (end - datetime.now(timezone.utc)).total_seconds())
        except ValueError:
            return 24 * 3600.0

    def _enqueue(self, task: dict, note: str) -> None:
        if task.get("budgeted"):
            self.agenda.hide_task(task["id"])
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
                                       self._default_engine, forge_settings.fallback())
        if engine is None:
            task["error"] = reason
            self._set_state(task, "failed", reason)
            self._notify(task, f"❌ Forge: nessun motore disponibile — {_esc(reason)}")
            return

        worktree = self.cfg.worktrees_path / task["id"]
        self._cleanup(task, delete_branch=True)  # idempotent restart
        base_branch = self._base_branch()
        base_sha = git_ops.rev(repo, base_branch)
        resume_from = task.get("resume_from")       # partial work kept when the Claude limit stopped it
        if resume_from:
            base_sha = task.get("resume_base") or base_sha
        git_ops.create_worktree(repo, worktree, task["branch"], resume_from or base_sha)
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

        workdoc = task.get("workdoc") or workdoc_name(task["id"], task["request"], task.get("created_at", ""))
        with self._lock:
            task["workdoc"] = workdoc
        src = (f"{task.get('requested_by') or 'user'} via {task.get('source') or 'hestia'} "
               f"-> Forge task {task['id']} [forge:{task['id']}]")
        context = str(task.get("context") or "") + notes_text(task)
        if resume_from:
            context += ("\n\nRIPRESA: il lavoro era stato fermato dal limite di Claude; quello già fatto è nel "
                        "commit corrente. Continua da lì, non ricominciare.")
        t0 = time.perf_counter()
        pieces = self._team_plan(task) if not resume_from else []
        if len(pieces) >= 2:
            # Cindy 31: one piece after the other in the same worktree, engine by difficulty.
            with self._lock:
                task["team"] = [{"title": p["title"], "difficulty": p["difficulty"], "state": "queued"}
                                for p in pieces]
            self._notify(task, f"🧩 Forge <code>{task['id'][:6]}</code>: lavoro diviso in {len(pieces)} pezzi.")
            summaries, all_ok = [], True
            for n, piece in enumerate(pieces):
                piece_engine = self._engine_for_piece(piece, engine)
                prompt = build_task_prompt(
                    f"[Pezzo {n + 1}/{len(pieces)}: {piece['title']}] {piece['request']}\n\nLavoro completo: "
                    f"{task['request']}", piece["services"] or task["services"], context, workdoc, src)
                result = self._engine_pass(task, piece_engine, worktree, prompt, test_runner)
                if result is None:
                    return
                with self._lock:
                    task["team"][n].update({"state": "done" if result.ok else "failed", "engine": piece_engine.name})
                summaries.append(f"{n + 1}. {piece['title']} ({piece_engine.name}): {result.summary[:400]}")
                all_ok = all_ok and result.ok
            from .engines import EngineResult
            result = EngineResult(all_ok, "\n".join(summaries), engine.name,
                                  log_tail=result.log_tail, turns=result.turns)
        else:
            prompt = build_task_prompt(task["request"], task["services"], context, workdoc, src)
            result = self._engine_pass(task, engine, worktree, prompt, test_runner)
            if result is None:
                return
        with self._lock:
            task.update({"summary": result.summary, "engine_log_tail": result.log_tail,
                         "turns": result.turns, "cost_usd": result.cost_usd,
                         "engine_ms": int((time.perf_counter() - t0) * 1000)})
            had_resume = task.pop("resume_from", None)
            task.pop("resume_base", None)
        if had_resume:  # the partial work is now in the task branch: the keep-alive ref can go
            git_ops.git(self.cfg.repo_path, "update-ref", "-d", f"refs/forge/resume/{task['id']}", check=False)

        sha = git_ops.commit_all(
            worktree, f"forge({task['id']}): {task['request'][:60]}\n\n{result.summary[:1500]}",
            self.cfg.git_author_name, self.cfg.git_author_email) or (
            git_ops.rev(worktree) if git_ops.changed_files(worktree, base_sha) else None)
        if not sha:
            self._cleanup(task, delete_branch=True)
            task["error"] = None if result.ok else result.summary[:500]
            self._set_state(task, "no_changes", "engine produced no diff")
            self._notify(task, (
                f"⚠️ Forge <code>{task['id'][:6]}</code>: nessuna modifica prodotta.\n"
                f"{_esc(result.summary[:500])}"))
            return

        self._review(task, worktree, base_sha, sha, result.summary, result.ok, engine=engine,
                     test_runner=test_runner)

    # ── engine pass, Claude limit, team plan (Cindy 15 + 31) ────────────────
    def _engine_pass(self, task: dict, engine, worktree: Path, prompt: str, test_runner):
        """One engine run in the task worktree. None = stopped by the Claude usage limit (already handled)."""
        self.artifacts.start_transcript(task["id"], prompt, engine.name)
        result = engine.run(worktree, prompt, test_runner,
                            on_event=lambda ev: self.artifacts.append(task["id"], ev))
        if engine.name == "claude":
            self.artifacts.import_claude(task["id"])
        self.artifacts.write_text(task["id"], "engine.log", result.log_tail)
        if engine.name == "claude" and not result.ok and self.claude_budget.looks_like_limit(
                f"{result.summary} {result.log_tail}"):
            self._wait_for_limit(task, worktree)
            return None
        return result

    LIMIT_MAX_RESTARTS = 3

    def _wait_for_limit(self, task: dict, worktree: Path) -> None:
        """Claude limit: the task waits for the reset instead of failing (Cindy 15). Partial work is kept on
        ``refs/forge/resume/<id>``; a one-off agenda task at the reset time resumes it («continua»)."""
        until = self.claude_budget.mark_exhausted()
        self._save_settings()
        # A fact for the presence engine ("Stanco" overlay): no Claude quota left until the reset.
        self.presence.signal("resource.claude_quota_left", 0, meta={"until": until},
                             ttl_seconds=self._seconds_until(until))
        partial = git_ops.commit_all(worktree, f"forge({task['id']}): lavoro parziale prima del limite",
                                     self.cfg.git_author_name, self.cfg.git_author_email)
        head = git_ops.rev(worktree)
        progressed = bool(partial) or head != task.get("resume_from")
        if head != task.get("base_sha"):
            git_ops.git(self.cfg.repo_path, "update-ref", f"refs/forge/resume/{task['id']}", head, check=False)
        with self._lock:
            if head != task.get("base_sha"):
                task["resume_base"] = task.get("resume_base") or task.get("base_sha")
                task["resume_from"] = head
            task["limit_restarts"] = 0 if progressed else int(task.get("limit_restarts") or 0) + 1
            restarts = task["limit_restarts"]
        self._cleanup(task, delete_branch=True)
        if restarts >= self.LIMIT_MAX_RESTARTS:
            task["error"] = "Claude usage limit reached, no progress after 3 restarts"
            self._set_state(task, "failed", f"Claude usage limit: {restarts} restarts without progress")
            self._notify(task, f"⛔ Forge <code>{task['id'][:6]}</code>: fermo al limite di Claude per "
                               f"{restarts} volte senza progressi. Riprova a mano quando vuoi.")
            return
        if task.get("budgeted"):
            self._set_state(task, "scheduled", f"Claude usage limit: paused until {until}")
        else:
            self._set_state(task, "waiting_limit", f"Claude usage limit: resumes at {until}")
            import random
            at = datetime.fromisoformat(until) if "T" in str(until) else datetime.now(timezone.utc)
            at = (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) + timedelta(seconds=random.randint(30, 90))
            self.agenda.plan(f"forge.resume.{task['id']}", f"Forge: riprendi {task['request'][:60]}", at,
                             action={"service": "hephaestus", "method": "POST",
                                     "path": f"/api/hephaestus/forge/tasks/{task['id']}/resume",
                                     "timeout_seconds": 30},
                             description="Riprende il task di sviluppo fermato dal limite di Claude.")
        self._notify(task, f"⏸ Limite di Claude raggiunto. Il lavoro <code>{task['id'][:6]}</code> riprende "
                           f"da dove era alle {_esc(str(until)[11:16] or str(until)[:16])}.")

    def resume(self, task_id: str, by: str = "agenda") -> dict[str, Any]:
        """One-off agenda task at the Claude reset (or the owner): a task waiting for the limit starts again."""
        task = self._require(task_id)
        if task.get("state") != "waiting_limit":
            return {**task, "resumed": False}
        self._enqueue(task, f"resumed after the Claude limit by {by}")
        return task

    def _team_plan(self, task: dict) -> list[dict]:
        if task.get("external") or len(task.get("services") or []) < forge_settings.get_int(
                forge_settings.TEAM_MIN_SERVICES, 1):
            return []
        return self.reviewer.plan(task["request"], task.get("services") or [])

    def _engine_for_piece(self, piece: dict, default):
        wanted = "oracle" if piece.get("difficulty") == "semplice" else "claude"
        engine = self.engines.get(wanted)
        if engine is not None and engine.available()[0]:
            return engine
        return default

    def _run_tests(self, task: dict, worktree: Path, base_sha: str) -> tuple[list[str], Any, str]:
        changed = git_ops.changed_files(worktree, base_sha)
        tests_ok, tests_out = run_test_command(
            worktree, self.cfg.test_cmd, self._test_paths(worktree, changed, task["services"]))
        self.artifacts.write_text(task["id"], "tests.txt", tests_out)
        return changed, tests_ok, tests_out

    def _auto_review(self, task: dict, worktree: Path, base_sha: str, summary: str, tests_out: str) -> dict:
        acceptance = forge_review.acceptance_from_workdoc(worktree, task.get("workdoc") or "")
        return self.reviewer.review(request=task["request"], acceptance=acceptance,
                                    diff=git_ops.diff(worktree, base_sha, max_chars=60000),
                                    tests=tests_out, summary=summary)

    def _review(self, task: dict, worktree: Path, base_sha: str, sha: str, summary: str, engine_ok: bool,
                heading: str = "Forge: modifica pronta", engine=None, test_runner=None) -> None:
        """Forge's own tests, the automatic review (+ one round of fixes by the engine), then the owner's
        approval (or auto merge when allowed)."""
        changed, tests_ok, tests_out = self._run_tests(task, worktree, base_sha)
        self._set_state(task, "reviewing", f"tests_ok={tests_ok}")
        review = self._auto_review(task, worktree, base_sha, summary, tests_out)
        review["rounds"] = 0
        if review["blocking"] and engine is not None:
            fix = self._engine_pass(task, engine, worktree, forge_review.fix_prompt(review["issues"]), test_runner)
            if fix is None:
                return                          # Claude limit: the task waits and resumes later
            review["rounds"] = 1
            new_sha = git_ops.commit_all(worktree, f"forge({task['id']}): correzioni della revisione\n\n"
                                         f"{fix.summary[:1000]}", self.cfg.git_author_name, self.cfg.git_author_email)
            if new_sha:
                sha, summary = new_sha, f"{summary}\n\nCorrezioni dopo la revisione: {fix.summary[:600]}"
                engine_ok = engine_ok and fix.ok
                changed, tests_ok, tests_out = self._run_tests(task, worktree, base_sha)
                second = self._auto_review(task, worktree, base_sha, summary, tests_out)
                review = {**second, "rounds": 1, "first": review["issues"]}
        self.artifacts.write_text(task["id"], "review.json", json.dumps(review, ensure_ascii=False, indent=1))
        with self._lock:
            task.update({
                "commit_sha": sha,
                "changed_files": changed,
                "touched_services": services_from_paths(changed),
                "diff_stat": git_ops.diff_stat(worktree, base_sha),
                "tests": {"ok": tests_ok, "output_tail": tests_out[-3000:]},
                "review": review,
                "summary": summary,
            })
        if forge_settings.get_bool(forge_settings.PUSH_BRANCH):
            try:
                git_ops.push(worktree, task["branch"])
            except Exception as exc:
                logger.warning("[🔄] event=forge_push_failed task_id=%s error=%s", task["id"], exc)

        self._set_state(task, "awaiting_review", f"engine_ok={engine_ok} tests_ok={tests_ok}")
        tests_label = {True: "✅ test ok", False: "❌ test falliti", None: "➖ nessun test"}[tests_ok]
        short = task["id"][:6]
        self._notify(task, (
            f"🧩 <b>{_esc(heading)}</b> <code>{short}</code> · {tests_label}\n"
            f"{_esc(summary[:900])}\n\n{_esc(forge_review.card(review))}\n\n"
            f"<pre>{_esc(task['diff_stat'][-900:])}</pre>\n"
            f"Rispondi \"approva sviluppo {short}\" per applicarla, \"rifiuta {short}\" per scartarla."))

        if task.get("auto_merge") and tests_ok is True and engine_ok and not review.get("blocking"):
            with self._lock:
                task["approved_by"] = "policy:auto_merge"
            self._set_state(task, "approved", "auto_merge policy")
            self._merge_and_deploy(task, "policy:auto_merge")

    def _run_external(self, task: dict) -> None:
        """A branch made elsewhere (forge_submit_branch): fetch → worktree → Forge's tests → approval."""
        repo = self.cfg.repo_path
        ext = task["external"]
        branch, by = ext["branch"], ext.get("by") or "user"
        worktree = self.cfg.worktrees_path / task["id"]
        self._cleanup(task, delete_branch=True)
        base_branch = self._base_branch()
        base_sha = git_ops.rev(repo, base_branch)
        try:
            head = git_ops.fetch_branch(repo, branch)
        except git_ops.GitError as exc:
            with self._lock:
                ext["pending"] = False
                task["error"] = f"fetch {branch}: {exc}"[:1000]
            self._set_state(task, "failed", f"external branch {branch} not fetched: {exc}")
            self._notify(task, f"❌ Forge <code>{task['id'][:6]}</code>: branch <code>{_esc(branch)}</code> "
                               f"non scaricato da origin — {_esc(str(exc)[:300])}")
            return
        git_ops.create_worktree(repo, worktree, task["branch"], head)
        with self._lock:
            task.update({"worktree": str(worktree), "base_branch": base_branch, "base_sha": base_sha,
                         "engine": "external"})
        self._set_state(task, "running", f"external branch {branch}@{head[:8]} by {by}")
        if not git_ops.changed_files(worktree, base_sha):
            self._cleanup(task, delete_branch=True)
            with self._lock:
                ext["pending"] = False
            self._set_state(task, "no_changes", f"branch {branch} has nothing new on {base_branch}")
            self._notify(task, f"⚠️ Forge <code>{task['id'][:6]}</code>: il branch <code>{_esc(branch)}</code> "
                               f"non cambia nulla rispetto a {_esc(base_branch)}.")
            return
        summary = ext.get("summary") or f"Branch {branch}"
        with self._lock:
            ext["pending"] = False
            task["summary"] = f"{summary}\n\n(branch {branch} di {by})"
        self._review(task, worktree, base_sha, head, task["summary"], True,
                     heading=f"Forge: correzione esterna pronta ({by})")

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

        dplan = deployer.plan(self.cfg.repo_path, task.get("changed_files") or [])
        task["deploy_plan"] = {"restart": dplan.restart, "rebuild": dplan.rebuild,
                               "restart_self": dplan.restart_self}
        services = dplan.restart
        rebuild_note = (f"\n🔧 Da ricostruire a mano: <code>up-all.bat --build {' '.join(dplan.rebuild)}</code>"
                        if dplan.rebuild else "")
        if not self.cfg.deploy_cmd or not (services or dplan.restart_self):
            self._notify(task, (
                f"✅ <b>Forge: applicata</b> <code>{task['id'][:6]}</code> (merge {merge_sha[:8]}).\n"
                + (f"Riavvia: {', '.join(services + (['hephaestus'] if dplan.restart_self else []))}."
                   if (services or dplan.restart_self) else "") + rebuild_note))
            return

        ok, out = self._deploy(services) if services else (True, "")
        task["deploy"] = {"ok": ok, "output_tail": out[-2000:]}
        self.artifacts.write_text(task["id"], "deploy.log", out)
        unhealthy = self._unhealthy(services) if ok and services else ([] if ok else services)
        if ok and not unhealthy:
            self._set_state(task, "deployed", f"{dplan.summary()}")
            self._notify(task, (
                f"🚀 <b>Forge: in produzione</b> <code>{task['id'][:6]}</code> → {_esc(dplan.summary())}.\n"
                f"Rollback: \"rollback sviluppo {task['id'][:6]}\"." + rebuild_note))
            if dplan.restart_self:
                self._restart_self()
            return
        why = f"deploy_ok={ok} unhealthy={unhealthy}"
        if forge_settings.get_bool(forge_settings.AUTO_ROLLBACK):
            self._do_rollback(task, f"auto: {why}")
        else:
            self._notify(task, f"⚠️ Forge <code>{task['id'][:6]}</code>: deploy problematico ({_esc(why)}).")

    def _restart_self(self) -> None:
        """Hephaestus restarts itself last (state already saved; resumes on boot)."""
        def _later():
            time.sleep(3)
            deployer.restart_containers(["hephaestus"]) if self.cfg.deploy_cmd == "builtin" else None
        threading.Thread(target=_later, daemon=True, name="forge-self-restart").start()

    def _do_rollback(self, task: dict, note: str) -> None:
        revert_sha = git_ops.revert_merge(self.cfg.repo_path, task["merge_sha"],
                                          self.cfg.git_author_name, self.cfg.git_author_email)
        with self._lock:
            task["revert_sha"] = revert_sha
        services = (task.get("deploy_plan") or {}).get("restart") or []
        if self.cfg.deploy_cmd and services:
            self._deploy(services)
        self._set_state(task, "rolled_back", f"revert {revert_sha[:8]} {note}")
        self._notify(task, f"↩️ <b>Forge: rollback</b> <code>{task['id'][:6]}</code> ({_esc(note[:200])}).")

    def _deploy(self, services: list[str]) -> tuple[bool, str]:
        if self.cfg.deploy_cmd == "builtin":
            return deployer.restart_containers(services)
        cmd = self.cfg.deploy_cmd.replace("{services}", " ".join(services))
        try:
            proc = subprocess.run(cmd, shell=True, cwd=str(self.cfg.repo_path),
                                  capture_output=True, text=True, timeout=1200)
        except subprocess.TimeoutExpired:
            return False, "deploy timed out"
        return proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")

    def deploying_services(self) -> set[str]:
        """Services a Forge deploy is restarting right now (merged, not yet deployed/rolled back): the immune
        system leaves them to Forge's own health check and rollback (oracle-offline v3 B)."""
        with self._lock:
            tasks = [dict(t) for t in self._tasks.values()] if isinstance(self._tasks, dict) else []
        out: set[str] = set()
        for t in tasks:
            if t.get("state") == "merged":
                out.update((t.get("deploy_plan") or {}).get("restart") or [])
        return out

    def unhealthy(self, services: list[str]) -> list[str]:
        """Health check through Hub after the verify delay (deploys and the immune system's restarts)."""
        return self._unhealthy(services)

    def _unhealthy(self, services: list[str]) -> list[str]:
        wait_seconds(forge_settings.get_int(forge_settings.VERIFY_DELAY, 0))
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
        """Hermes direct send to the requester + system event for subscriptions.

        A concrete target (the Telegram chat that asked) → only that client;
        otherwise ``owner`` → every client (Hermes global notifications)."""
        hub = self.cfg.hub_api_url
        target = task.get("notify_target") or self.cfg.notify_target or "owner"

        def _route(path: str, body: dict) -> None:
            requests.post(f"{hub}/route/hermes/{path}",
                          json={"method": "POST", "headers": {}, "query": {}, "body": body,
                                "timeout_seconds": 8}, timeout=10)

        try:
            _route("api/dispatch/send", {"channel": "telegram" if target != "owner" else "",
                                         "target": str(target), "message": text,
                                         "metadata": {"source": "hephaestus", "type": "hephaestus.forge"}})
            _route("api/events/ingest", {
                "domain": "system", "event_type": "hephaestus.forge", "entity_id": task["id"],
                "payload": {"_message": text, "task_id": task["id"], "state": task.get("state")}})
        except Exception as exc:
            logger.warning("[🔄] event=forge_notify_failed task_id=%s error=%s", task["id"], exc)


def _esc(text: str) -> str:
    import html
    return html.escape(str(text or ""))


def notes_text(task: dict) -> str:
    """Notes on a task (owner, external AI) as prompt context for the engine."""
    notes = task.get("notes") or []
    if not notes:
        return ""
    lines = [f"- [{n.get('by')}] {' '.join(str(n.get('text') or '').split())[:1500]}" for n in notes[-10:]]
    return "\nNote sul task (analisi e indicazioni):\n" + "\n".join(lines)

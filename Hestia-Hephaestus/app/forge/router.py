"""HTTP surface of Forge: /api/hephaestus/forge/*"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from .inspector import TaskInspector
from .repo_browser import RepoBrowser, RepoError
from .service import Forge, ForgeError


class ForgeTaskRequest(BaseModel):
    request: str = Field(..., description="What to build or fix, in natural language")
    services: list[str] = Field(default_factory=list)
    engine: str = ""
    source: str = "user"
    requested_by: str = "user"
    auto_start: bool | None = Field(None, description="None = user→start, Athena/Argus→permission mode")
    auto_merge: bool | None = None
    context: str = ""
    notify_target: str = ""
    workdoc: str = Field("", description="continue docs/work/<workdoc>/ of an earlier task")
    parent_task: str = Field("", description="follow-up of this task: inherits workdoc + services + context")


class ForgeEngineChoice(BaseModel):
    engine: str = Field(..., description="local | cloud | claude")


class ForgeModeChoice(BaseModel):
    mode: str = Field(..., description="ask | auto | full_auto")
    group: str = Field("", description="local | cloud (empty = both)")


class ForgeDecision(BaseModel):
    by: str = "user"
    reason: str = ""
    now: bool = False   # approve: skip the Claude budget window (user asked "subito")


class ClaudeScheduleChange(BaseModel):
    reset_day: str | None = Field(None, description="mon..sun / lun..dom")
    reset_time: str | None = Field(None, description="HH:MM local")
    tz: str | None = None
    window_hours: int | None = None
    night: str | None = Field(None, description="HH:MM-HH:MM")
    night_max_tasks: int | None = None
    final_hours: int | None = None


def create_forge_router(forge: Forge) -> APIRouter:
    router = APIRouter(prefix="/api/hephaestus/forge", tags=["forge"])

    def _guard(fn, *args, **kwargs) -> Any:
        try:
            return fn(*args, **kwargs)
        except ForgeError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @router.get("/status")
    def forge_status() -> dict[str, Any]:
        return forge.status()

    @router.get("/engine")
    def forge_engine_get() -> dict[str, Any]:
        st = forge.status()
        return {"status": "ok", "default_engine": st["engine_default"],
                "fallback": st["engine_fallback"], "engines": st["engines"]}

    @router.post("/engine")
    def forge_engine_set(body: ForgeEngineChoice) -> dict[str, Any]:
        return {"status": "ok", **_guard(forge.set_default_engine, body.engine)}

    @router.get("/settings")
    def forge_settings_get() -> dict[str, Any]:
        return {"status": "ok", **forge.settings()}

    @router.post("/settings/mode")
    def forge_mode_set(body: ForgeModeChoice) -> dict[str, Any]:
        return {"status": "ok", **_guard(forge.set_mode, body.mode, body.group)}

    @router.get("/claude-budget")
    def forge_claude_budget() -> dict[str, Any]:
        return {"status": "ok", **forge.claude_budget.status()}

    @router.post("/settings/claude-schedule")
    def forge_claude_schedule(body: ClaudeScheduleChange) -> dict[str, Any]:
        return {"status": "ok", **_guard(forge.set_claude_schedule, **body.model_dump())}

    @router.post("/tasks")
    def forge_submit(req: ForgeTaskRequest) -> dict[str, Any]:
        task = _guard(forge.submit, **req.model_dump())
        return {"status": "ok", "task": _public(task)}

    @router.get("/tasks")
    def forge_list(state: str | None = None, limit: int = 20) -> dict[str, Any]:
        rows = forge.list(state=state, limit=limit)
        return {"status": "ok", "count": len(rows), "tasks": [_public(t) for t in rows]}

    @router.get("/tasks/{task_id}")
    def forge_get(task_id: str) -> dict[str, Any]:
        task = forge.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return {"status": "ok", "task": task}

    @router.get("/tasks/{task_id}/diff", response_class=PlainTextResponse)
    def forge_diff(task_id: str) -> str:
        return _guard(forge.diff, task_id)

    # ── Sviluppo page: task detail ─────────────────────────────────────────
    inspector = TaskInspector(forge)

    def _inspect(fn, task_id: str, *args) -> Any:
        try:
            return {"status": "ok", **fn(task_id, *args)}
        except ForgeError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/tasks/{task_id}/transcript")
    def forge_transcript(task_id: str, offset: int = 0, limit: int = 500) -> dict[str, Any]:
        task = _guard(forge._require, task_id)
        try:
            data = forge.artifacts.transcript(task["id"], offset, limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"status": "ok", "task_id": task["id"], "state": task.get("state"), **data}

    @router.get("/tasks/{task_id}/files")
    def forge_files(task_id: str, diff: bool = True) -> dict[str, Any]:
        return _inspect(inspector.files, task_id, diff)

    @router.get("/tasks/{task_id}/workdoc")
    def forge_workdoc(task_id: str) -> dict[str, Any]:
        return _inspect(inspector.workdoc, task_id)

    @router.get("/tasks/{task_id}/tests")
    def forge_tests(task_id: str) -> dict[str, Any]:
        return _inspect(inspector.tests, task_id)

    @router.get("/tasks/{task_id}/logs")
    def forge_logs(task_id: str) -> dict[str, Any]:
        return _inspect(inspector.logs, task_id)

    @router.get("/tasks/{task_id}/events")
    def forge_events(task_id: str) -> dict[str, Any]:
        return _inspect(inspector.events, task_id)

    @router.post("/tasks/{task_id}/retry")
    def forge_retry(task_id: str, body: ForgeDecision | None = None) -> dict[str, Any]:
        b = body or ForgeDecision()
        task = _guard(forge.retry, task_id, b.by)
        return {"status": "ok", "task": _public(task)}

    @router.post("/tasks/{task_id}/approve")
    def forge_approve(task_id: str, body: ForgeDecision | None = None) -> dict[str, Any]:
        b = body or ForgeDecision()
        task = _guard(forge.approve, task_id, b.by, b.now)
        return {"status": "ok", "task": _public(task)}

    @router.post("/tasks/{task_id}/reject")
    def forge_reject(task_id: str, body: ForgeDecision | None = None) -> dict[str, Any]:
        b = body or ForgeDecision()
        task = _guard(forge.reject, task_id, b.reason, b.by)
        return {"status": "ok", "task": _public(task)}

    @router.post("/tasks/{task_id}/rollback")
    def forge_rollback(task_id: str, body: ForgeDecision | None = None) -> dict[str, Any]:
        b = body or ForgeDecision()
        task = _guard(forge.rollback, task_id, b.reason, b.by)
        return {"status": "ok", "task": _public(task)}

    return router


_PUBLIC_KEYS = ("id", "state", "request", "services", "engine", "engine_requested", "source", "requested_by",
                "summary", "diff_stat", "workdoc", "deploy_plan", "changed_files", "touched_services", "tests",
                "merge_sha", "branch", "error", "created_at", "updated_at", "cost_usd", "turns", "parent_task")


def _public(task: dict) -> dict:
    """Compact view for chat/LLM consumption (full record via GET /tasks/{id})."""
    out = {k: task.get(k) for k in _PUBLIC_KEYS if task.get(k) not in (None, "", [])}
    if isinstance(out.get("tests"), dict):
        out["tests"] = {"ok": out["tests"].get("ok"), "tail": str(out["tests"].get("output_tail", ""))[-500:]}
    return out


def create_repo_router(forge: Forge) -> APIRouter:
    """Read-only git browser of the Hestia checkout: /api/hephaestus/repo/*"""
    router = APIRouter(prefix="/api/hephaestus/repo", tags=["repo"])
    repo = RepoBrowser(forge.cfg.repo_path, forge._base_branch)

    def _guard(fn, *args) -> dict[str, Any]:
        try:
            return {"status": "ok", **fn(*args)}
        except RepoError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @router.get("/branches")
    def repo_branches() -> dict[str, Any]:
        return _guard(repo.branches)

    @router.get("/tags")
    def repo_tags() -> dict[str, Any]:
        return _guard(repo.tags)

    @router.get("/log")
    def repo_log(ref: str = "", path: str = "", limit: int = 100, skip: int = 0, all: bool = False) -> dict[str, Any]:
        return _guard(repo.log, ref, path, limit, skip, all)

    @router.get("/commits/{sha}")
    def repo_commit(sha: str) -> dict[str, Any]:
        return _guard(repo.commit, sha)

    @router.get("/compare")
    def repo_compare(base: str = "", head: str = "HEAD") -> dict[str, Any]:
        return _guard(repo.compare, base, head)

    @router.get("/tree")
    def repo_tree(ref: str = "", path: str = "") -> dict[str, Any]:
        return _guard(repo.tree, ref, path)

    @router.get("/file")
    def repo_file(ref: str = "", path: str = "") -> dict[str, Any]:
        return _guard(repo.file, ref, path)

    @router.get("/dossiers")
    def repo_dossiers(ref: str = "") -> dict[str, Any]:
        return _guard(repo.dossiers, ref)

    return router

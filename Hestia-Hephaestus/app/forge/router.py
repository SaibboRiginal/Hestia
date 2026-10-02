"""HTTP surface of Forge: /api/hephaestus/forge/*"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

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


class ForgeEngineChoice(BaseModel):
    engine: str = Field(..., description="local | cloud | claude")


class ForgeModeChoice(BaseModel):
    mode: str = Field(..., description="ask | auto | full_auto")
    group: str = Field("", description="local | cloud (empty = both)")


class ForgeDecision(BaseModel):
    by: str = "user"
    reason: str = ""


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

    @router.post("/tasks/{task_id}/approve")
    def forge_approve(task_id: str, body: ForgeDecision | None = None) -> dict[str, Any]:
        task = _guard(forge.approve, task_id, (body or ForgeDecision()).by)
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


_PUBLIC_KEYS = ("id", "state", "request", "services", "engine", "source", "summary", "diff_stat",
                "changed_files", "touched_services", "tests", "merge_sha", "branch", "error",
                "created_at", "updated_at", "cost_usd")


def _public(task: dict) -> dict:
    """Compact view for chat/LLM consumption (full record via GET /tasks/{id})."""
    out = {k: task.get(k) for k in _PUBLIC_KEYS if task.get(k) not in (None, "", [])}
    if isinstance(out.get("tests"), dict):
        out["tests"] = {"ok": out["tests"].get("ok"), "tail": str(out["tests"].get("output_tail", ""))[-500:]}
    return out

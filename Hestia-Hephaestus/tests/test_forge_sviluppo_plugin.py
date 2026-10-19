"""Sviluppo page as a Hephaestus plugin (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4, §B5):
badge counts and «Copia per AI» markdown, built from the forge_task / forge_tasks views.

Markers: unit, api
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.forge.export import export_markdown
from app.forge.router import counts, create_forge_router
from app.forge.service import BRANCH_SUBMIT_STATES, USER_SOURCES

from test_forge_external import _forge   # same minimal Forge double


def _client(forge) -> TestClient:
    app = FastAPI()
    app.include_router(create_forge_router(forge))
    return TestClient(app)


def _task(forge, request: str, state: str, **extra) -> dict:
    task = forge.submit(request=request, source=extra.pop("source", "ui"))
    try:
        forge._queue.get_nowait()
    except Exception:
        pass
    task["state"] = state
    task.update(extra)
    return task


@pytest.mark.unit
def test_counts_review_is_awaiting_review_plus_proposed():
    rows = [{"state": s} for s in ("awaiting_review", "proposed", "proposed", "running", "deployed", "failed")]
    c = counts(rows)
    assert c["review"] == 3 and c["awaiting_review"] == 1 and c["proposed"] == 2
    assert c["running"] == 1 and c["open"] == 4 and c["by_state"]["deployed"] == 1 and c["total"] == 6


@pytest.mark.unit
def test_export_markdown_says_how_to_submit_a_fix():
    t = {"id": "abcdef123456", "state": "failed", "request": "Correggi l'export ICS", "workdoc": "2026-10-01-ics",
         "error": "pytest: 2 failed", "source": "athena", "notes": [{"ts": "t", "by": "x", "text": "vedi tz"}]}
    md = export_markdown([t], ["abcdef · failed · Correggi"], BRANCH_SUBMIT_STATES, USER_SOURCES)
    assert "Correggi l'export ICS" in md and "pytest: 2 failed" in md
    assert "docs/work/2026-10-01-ics/" in md and "proposto da athena" in md and "vedi tz" in md
    assert 'forge_submit_branch(task_id="abcdef"' in md and "forge_task_note" in md
    closed = export_markdown([{**t, "state": "deployed"}], [], BRANCH_SUBMIT_STATES, USER_SOURCES)
    assert "forge_submit_branch(" not in closed and "non accetta un branch" in closed


@pytest.mark.api
def test_counts_endpoint(monkeypatch):
    forge = _forge(monkeypatch)
    _task(forge, "Aggiungi il widget meteo", "awaiting_review")
    _task(forge, "Sistema il calendario mobile", "proposed")
    body = _client(forge).get("/api/hephaestus/forge/counts").json()
    assert body["status"] == "ok" and body["review"] == 2


@pytest.mark.api
def test_export_endpoint_short_ids_missing_and_dedup(monkeypatch):
    forge = _forge(monkeypatch)
    a = _task(forge, "Aggiungi il widget meteo alla home", "failed", error="boom")
    b = _task(forge, "Sistema il calendario sul telefono", "proposed")
    c = _client(forge)
    r = c.get("/api/hephaestus/forge/tasks/export", params={"ids": f"{a['id'][:6]},{a['id']},{b['id']},zzzzzz"})
    body = r.json()
    assert r.status_code == 200 and body["count"] == 2 and body["missing"] == ["zzzzzz"]
    assert "widget meteo" in body["markdown"] and "calendario" in body["markdown"] and "boom" in body["markdown"]
    assert body["filename"].endswith(".md")
    assert c.get("/api/hephaestus/forge/tasks/export").status_code == 400
    assert c.get("/api/hephaestus/forge/tasks/export", params={"ids": "nope99"}).status_code == 404
    # the export never shadows the task detail route
    assert c.get(f"/api/hephaestus/forge/tasks/{a['id']}").json()["task"]["id"] == a["id"]

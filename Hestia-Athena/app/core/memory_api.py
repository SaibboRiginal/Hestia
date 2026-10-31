"""Learning log, memory review and docs check endpoints + MCP tools (dossier
docs/work/2026-10-24-tutto-brainstorm-cindy W3: Cindy 8, 18, 29)."""
from __future__ import annotations

import logging
import os
from typing import Any

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import docs_check
from .learning import Learning

logger = logging.getLogger("hestia_athena.memory_api")

_HUB = os.getenv("HUB_API_URL", "http://hestia_hub:19001/api").rstrip("/")
learning = Learning(_HUB)
router = APIRouter()
DOCS_JOB = "athena.docs_check"


def _publish(event_type: str, entity_id: str, payload: dict) -> None:
    try:
        requests.post(f"{_HUB}/route/hermes/api/events/ingest",
                      json={"method": "POST", "headers": {}, "query": {}, "timeout_seconds": 6,
                            "body": {"event_type": event_type, "domain": "assistant", "entity_id": entity_id,
                                     "payload": payload}}, timeout=8)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[🔄] event=athena_publish_failed entity=%s error=%s", entity_id, exc)


def _list_tools() -> list[dict]:
    from hestia_common.mcp_client import MCPClient
    return MCPClient(_HUB, "athena", timeout=20).list_tools(refresh=True)


@router.get("/api/athena/learning")
def learning_log(limit: int = 50) -> dict[str, Any]:
    rows = learning.log(max(1, min(int(limit), 200)))
    return {"count": len(rows), "items": rows}


@router.post("/api/athena/learning/{entry_id}/undo")
def learning_undo(entry_id: str, body: dict | None = None):
    status, out = learning.undo(entry_id, by=str((body or {}).get("by") or "user"))
    return JSONResponse(status_code=status, content=out)


@router.post("/api/athena/memory/review")
def memory_review() -> dict[str, Any]:
    return learning.review(_publish)


@router.get("/api/athena/memory/proposals")
def memory_proposals() -> dict[str, Any]:
    """Clean-up proposals still waiting for the owner (page «Cosa ho imparato»)."""
    rows = learning.pending_proposals()
    return {"count": len(rows), "items": rows}


@router.post("/api/athena/memory/proposals/{pid}/apply")
def memory_proposal_apply(pid: str, body: dict | None = None):
    status, out = learning.apply(pid, by=str((body or {}).get("by") or "user"))
    return JSONResponse(status_code=status, content=out)


@router.post("/api/athena/memory/proposals/{pid}/dismiss")
def memory_proposal_dismiss(pid: str, body: dict | None = None):
    status, out = learning.dismiss(pid, by=str((body or {}).get("by") or "user"))
    return JSONResponse(status_code=status, content=out)


@router.post("/api/athena/docs/check")
def docs_check_run(propose: bool = True) -> dict[str, Any]:
    """Agenda job ``athena.docs_check`` (monthly) and tool ``docs_check``: proposals to Forge, never edits."""
    found = docs_check.findings(learning._route, _list_tools)
    sent = 0
    if propose:
        for f in found:
            status, _ = learning._route("hephaestus", "POST", "api/hephaestus/forge/tasks", {
                "request": docs_check.request_text(f), "source": "athena", "requested_by": "athena.docs_check",
                "services": [f["module"]], "context": "Controllo mensile documenti ↔ codice (Cindy 29)."})
            sent += int(bool(status) and status < 400)
    logger.info("event=athena_docs_check modules=%d proposals=%d", len(found), sent)
    return {"findings": found, "proposals": sent}


def agenda_rules() -> list[dict]:
    from hestia_common.agenda_client import job_rule
    return [job_rule(DOCS_JOB, "Documenti allineati al codice", service="athena", path="/api/athena/docs/check",
                     recurrence="FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=4;BYMINUTE=30", timeout_seconds=180,
                     description="Una volta al mese confronto la documentazione con quello che i moduli fanno "
                                 "davvero e propongo le correzioni allo sviluppo (le approvi tu).")]


def mcp_tools() -> list:
    from hestia_common.mcp_helpers import MCPTool

    def tool(name, description, method, path, title, *, params=None, required=None, label="", section="Memoria",
             group="memoria", prompt=""):
        schema = {"type": "object", "properties": params or {}}
        if required:
            schema["required"] = required
        return MCPTool(name=name, description=description, parameters=schema,
                       handler=lambda **kw: {"status": "ok", "tool": name, "params": kw}, title=title,
                       method=method, path=path, clients=["telegram", "ui", "external"], response_prompt=prompt,
                       telegram_group=group, telegram={"section": section, **({"label": label} if label else {})})

    return [
        tool("memory_rivedi", "«Rivedi cosa sai di me»: cerca doppioni, contraddizioni e cose vecchie nella memoria "
             "e le propone (l'utente conferma ognuna). Non cancella niente da solo.", "POST",
             "/api/athena/memory/review", "Rivedi cosa sai di me", label="Rivedi memoria"),
        tool("memory_learning", "Cosa ha imparato l'assistente di recente (memorie aggiunte, tolte, rinforzate), con "
             "le parole esatte dell'utente da cui viene ogni cosa.", "GET", "/api/athena/learning",
             "Cosa ho imparato", params={"limit": {"type": "integer"}}, label="Cosa ho imparato",
             prompt="Elenco breve: cosa, quando, la frase da cui viene. Niente id."),
        tool("memory_learning_undo", "Annulla una cosa imparata (id da memory_learning).", "POST",
             "/api/athena/learning/{entry_id}/undo", "Annulla cosa imparata", params={"entry_id": {"type": "string"}},
             required=["entry_id"]),
        tool("memory_proposals", "Le pulizie della memoria proposte da «Rivedi cosa sai di me» che aspettano ancora "
             "una risposta (doppioni, contraddizioni, cose vecchie).", "GET", "/api/athena/memory/proposals",
             "Pulizie da decidere", label="Pulizie da decidere",
             prompt="Elenco breve: cosa propone e perché. Niente id."),
        tool("memory_proposal_apply", "Applica una pulizia proposta (id da memory_proposals): solo se l'utente dice sì.",
             "POST", "/api/athena/memory/proposals/{pid}/apply", "Applica pulizia", params={"pid": {"type": "string"}},
             required=["pid"]),
        tool("memory_proposal_dismiss", "Scarta una pulizia proposta (id da memory_proposals).", "POST",
             "/api/athena/memory/proposals/{pid}/dismiss", "Scarta pulizia", params={"pid": {"type": "string"}},
             required=["pid"]),
        tool("docs_check", "Controlla se la documentazione del repo segue il codice e propone le correzioni allo "
             "sviluppo.", "POST", "/api/athena/docs/check", "Controlla i documenti", section="Sviluppo",
             group="sviluppo", label="Controlla documenti"),
    ]

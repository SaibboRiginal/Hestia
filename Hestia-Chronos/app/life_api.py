"""Routines, special events, smart calendar, manual presence (dossier docs/work/2026-10-24-tutto-brainstorm-cindy W2).

REST endpoints (``router``), the MCP tools for them (``mcp_tools()``, appended to Chronos' list so they are on
Telegram, WebUI and the external MCP too) and the agenda rules they need (``boot_rules()``).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import agenda, routines, smart_calendar, special
from services import presence as assistant_presence
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

logger = logging.getLogger("hestia_chronos.life_api")

router = APIRouter()


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except agenda.AgendaError as exc:
        raise HTTPException(status_code=getattr(exc, "status_code", 400) or 400, detail=str(exc))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ── routines (Cindy 7 + 27 + 28) ─────────────────────────────────────────────
class RoutineIn(BaseModel):
    title: str
    instruction: str
    recurrence: str | None = None
    start_at: str | None = None
    precheck: dict | None = None
    deliver: str = "hermes"
    on: dict | None = None


class TemplateIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    recurrence: str | None = None
    title: str = ""


class SignalIn(BaseModel):
    name: str
    data: dict[str, Any] = Field(default_factory=dict)


class MailRing(BaseModel):
    key: str
    reference_ids: list[str] = Field(default_factory=list)


@router.get("/api/routines")
def routines_list(include_cancelled: bool = False) -> dict:
    rows = _guard(routines.list_routines, include_cancelled)
    return {"count": len(rows), "items": rows}


@router.get("/api/routines/templates")
def routines_templates() -> dict:
    return {"templates": routines.TEMPLATES}


@router.post("/api/routines")
def routines_create(req: RoutineIn) -> dict:
    return _guard(routines.create, title=req.title, instruction=req.instruction, recurrence=req.recurrence,
                  start_at=req.start_at, precheck=req.precheck, deliver=req.deliver, on=req.on)


@router.post("/api/routines/from-template/{template_id}")
def routines_from_template(template_id: str, req: TemplateIn | None = None) -> dict:
    req = req or TemplateIn()
    return _guard(routines.from_template, template_id, req.values, recurrence=req.recurrence, title=req.title)


@router.post("/api/routines/signal")
def routines_signal(req: SignalIn) -> dict:
    return {"ok": True, "started": routines.on_signal(req.name, req.data)}


@router.post("/api/routines/mail")
def routines_mail(req: MailRing) -> dict:
    """Iris doorbell for mail-triggered routines."""
    return _guard(routines.on_mail, req.key, req.reference_ids)


class AnswerIn(BaseModel):
    question_id: str
    answer: str = ""
    client: str = ""


@router.post("/api/routines/{key}/answer")
def routines_answer(key: str, req: AnswerIn) -> dict:
    """Hermes: the owner answered a question of this routine (2026-10-30-domande-nelle-notifiche)."""
    return _guard(routines.answer, key, req.question_id, req.answer, req.client)


@router.post("/api/routines/{key}/run")
def routines_run(key: str) -> dict:
    """Agenda action and «Esegui adesso»."""
    return _guard(routines.run, key, by="agenda")


# ── special events (B6) ──────────────────────────────────────────────────────
class SpecialIn(BaseModel):
    title: str
    day: str
    kind: str = "custom"
    lead_days: int | None = None
    person: str = ""
    person_id: str = ""
    note: str = ""
    yearly: bool | None = None
    source: str = "utente"
    key: str = ""
    by: str = "user"


class SpecialProposal(BaseModel):
    title: str
    day: str
    kind: str = "custom"
    person: str = ""
    evidence: str = ""
    lead_days: int | None = None


@router.get("/api/special")
def special_list() -> dict:
    rows = special.list_special()
    return {"count": len(rows), "items": rows}


@router.post("/api/special")
def special_add(req: SpecialIn) -> dict:
    return _guard(special.add, **req.model_dump())


@router.delete("/api/special/{key}")
def special_remove(key: str) -> dict:
    return _guard(special.remove, key)


@router.post("/api/special/propose")
def special_propose(req: SpecialProposal) -> dict:
    return _guard(special.propose, **req.model_dump())


@router.post("/api/special/proposal/declined")
def special_declined(body: dict | None = None) -> dict:
    logger.info("event=special_proposal_declined")
    return {"ok": True}


@router.post("/api/special/run")
def special_run() -> dict:
    """Daily agenda job ``chronos.special.daily``."""
    return special.run_daily()


# ── smart calendar (B8) ──────────────────────────────────────────────────────
class KeptIn(BaseModel):
    event_id: str


@router.post("/api/calendar/smart/check")
def smart_check(days: int = 3) -> dict:
    return smart_calendar.check(days=max(1, min(14, int(days))))


@router.post("/api/calendar/smart/kept")
def smart_kept(req: KeptIn) -> dict:
    return smart_calendar.keep(req.event_id)


# ── manual presence (Telegram parity) ────────────────────────────────────────
class ManualIn(BaseModel):
    state: str
    minutes: float | None = None


@router.post("/api/presence/manual")
def presence_manual(req: ManualIn) -> dict:
    try:
        return assistant_presence.get_engine().set_manual(req.state, req.minutes)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown state {exc}")


@router.delete("/api/presence/manual")
def presence_manual_clear() -> dict:
    return assistant_presence.get_engine().clear_manual()


# ── agenda rules ─────────────────────────────────────────────────────────────
# The WebUI plugin calls only under its api_prefix /api/agenda/: the pages «Routine» and «Eventi speciali» reach
# the same handlers there (W7). The /api/routines and /api/special paths stay for modules and the tools.
for _path, _fn, _method in [("/api/agenda/routines", routines_list, "GET"), ("/api/agenda/routines", routines_create, "POST"),
                            ("/api/agenda/routines/templates", routines_templates, "GET"),
                            ("/api/agenda/routines/from-template/{template_id}", routines_from_template, "POST"),
                            ("/api/agenda/special", special_list, "GET"), ("/api/agenda/special", special_add, "POST"),
                            ("/api/agenda/special/{key}", special_remove, "DELETE")]:
    router.add_api_route(_path, _fn, methods=[_method])


def boot_rules() -> list[dict]:
    from hestia_common.agenda_client import job_rule
    return [
        job_rule("chronos.special.daily", tr("Hestia: special events"), service="chronos", path="/api/special/run",
                 recurrence="FREQ=DAILY;BYHOUR=8;BYMINUTE=0",
                 description="Every morning I remind you of birthdays and important dates (before and on the day)."),
        job_rule("chronos.smart_calendar", tr("Hestia: overlap check"), service="chronos",
                 path="/api/calendar/smart/check", recurrence="FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
                 description="Every morning I look at the next days: if two commitments overlap I propose where to move one. I don't move anything on my own."),
    ]


# ── MCP tools ────────────────────────────────────────────────────────────────
def mcp_tools() -> list:
    from hestia_common.mcp_helpers import MCPTool

    def tool(name, description, method, path, title, *, params=None, required=None, section="", label="",
             prompt="", group="giornata"):
        schema = {"type": "object", "properties": params or {}}
        if required:
            schema["required"] = required
        hints = {"section": section} if section else {}
        if label:
            hints["label"] = label
        return MCPTool(name=name, description=description, parameters=schema,
                       handler=lambda **kw: {"status": "ok", "tool": name, "params": kw},
                       title=title, method=method, path=path, clients=["telegram", "ui"],
                       response_mode="oracle_natural", response_prompt=prompt, telegram_group=group,
                       telegram=hints or None)

    s = {"type": "string"}
    return [
        tool("routine_list", "The user's routines (what they do, at what time or on which event they run, last run).",
             "GET", "/api/routines", "Your routines", section="Routine", label="Routine",
             prompt="Short list: name, when it runs, last time. No JSON."),
        tool("routine_templates", "The ready routine templates (news radar, new houses, expenses, week, mail).",
             "GET", "/api/routines/templates", "Routine templates", section="Routine", label="Models"),
        tool("routine_create",
             ("Create a routine in words: an instruction the assistant runs at a time (recurrence RRULE) or "
              "when something happens (on: {\"mail\": {\"senders\": ...}} or {\"signal\": name}). precheck = tool to "
              "call first (if it finds nothing the routine does not run). deliver: hermes (notification) or "
              "recap."),
             "POST", "/api/routines", "New routine", required=["title", "instruction"],
             params={"title": s, "instruction": {"type": "string", "description": "what to do, in words"},
                     "recurrence": {"type": "string", "description": "RRULE, e.g. FREQ=DAILY;BYHOUR=8;BYMINUTE=0"},
                     "start_at": s, "precheck": {"type": "object"}, "on": {"type": "object"},
                     "deliver": {"type": "string", "enum": ["hermes", "recap"]}},
             section="Routine", label="New routine"),
        tool("routine_from_template", "Create a routine from a template (id from routine_templates) with its fields.",
             "POST", "/api/routines/from-template/{template_id}", "Routine from a template", required=["template_id"],
             params={"template_id": s, "values": {"type": "object"}, "recurrence": s, "title": s},
             section="Routine"),
        tool("routine_run", "Run a routine now (key from routine_list).", "POST", "/api/routines/{key}/run",
             "Run routine", required=["key"], params={"key": s}, section="Routine"),
        tool("special_list", "Birthdays, anniversaries and important dates, with how many days are left.",
             "GET", "/api/special", "Special events", section="Special events", label="Special events",
             prompt="Short list by date: what, when, in how many days."),
        tool("special_add",
             ("Add a special event the user asked for (birthday, anniversary or other) and how many days "
              "before to remind. Birthdays and anniversaries repeat every year."),
             "POST", "/api/special", "Add special event", required=["title", "day"],
             params={"title": s, "day": {"type": "string", "description": "YYYY-MM-DD"},
                     "kind": {"type": "string", "enum": list(special.KINDS)}, "lead_days": {"type": "integer"},
                     "person": s, "note": s}, section="Special events"),
        tool("special_remove", "Remove a special event (key from special_list).", "DELETE", "/api/special/{key}",
             "Remove special event", required=["key"], params={"key": s}, section="Special events"),
        tool("special_propose",
             ("When you find an important date (in a mail, a conversation, the memory) the user did not ask to "
              "save: propose it, the user confirms with one tap."),
             "POST", "/api/special/propose", "Propose special event", required=["title", "day"],
             params={"title": s, "day": s, "kind": {"type": "string", "enum": list(special.KINDS)}, "person": s,
                     "evidence": {"type": "string", "description": "where you found it, one line"}},
             section="Special events"),
        tool("calendar_check",
             "Check the next days of the calendar: if two commitments overlap, propose where to move one.",
             "POST", "/api/calendar/smart/check", "Check overlaps", params={"days": {"type": "integer"}},
             section="Calendar", label="Overlaps"),
        tool("presence_set",
             ("Set the assistant's state by hand (e.g. focus, rest, out) for a time (minutes) or until the "
              "user clears it."), "POST", "/api/presence/manual", "Change status", required=["state"],
             params={"state": s, "minutes": {"type": "number"}}, section="Status", label="Change status",
             group="sistema"),
        tool("presence_clear", "Clear the state set by hand: the assistant decides by itself again.",
             "DELETE", "/api/presence/manual", "Automatic status", section="Status", label="Automatic status",
             group="sistema"),
        tool("presence_history", "The assistant's last state changes, with the reason.",
             "GET", "/api/presence/history", "Status history", params={"limit": {"type": "integer"}},
             section="Status", label="alt::Status history", group="sistema",
             prompt="Short list: when, from which state to which, why."),
    ]

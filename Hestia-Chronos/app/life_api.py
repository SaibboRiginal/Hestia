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
        job_rule("chronos.special.daily", "Hestia: eventi speciali", service="chronos", path="/api/special/run",
                 recurrence="FREQ=DAILY;BYHOUR=8;BYMINUTE=0",
                 description="Ogni mattina ti ricordo compleanni e date importanti (prima e il giorno stesso)."),
        job_rule("chronos.smart_calendar", "Hestia: controllo sovrapposizioni", service="chronos",
                 path="/api/calendar/smart/check", recurrence="FREQ=DAILY;BYHOUR=7;BYMINUTE=0",
                 description="Ogni mattina guardo i prossimi giorni: se due impegni si sovrappongono ti propongo "
                             "dove spostarne uno. Non sposto niente da solo."),
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
        tool("routine_list", "Le routine dell'utente (cosa fanno, quando o su quale evento partono, ultima esecuzione).",
             "GET", "/api/routines", "Le tue routine", section="Routine", label="Routine",
             prompt="Elenco breve: nome, quando parte, ultima volta. Niente JSON."),
        tool("routine_templates", "I modelli di routine pronti (radar notizie, case nuove, spese, settimana, mail).",
             "GET", "/api/routines/templates", "Modelli di routine", section="Routine", label="Modelli"),
        tool("routine_create",
             "Crea una routine a parole: un'istruzione che l'assistente esegue a un orario (recurrence RRULE) o "
             "quando succede qualcosa (on: {\"mail\": {\"senders\": ...}} o {\"signal\": nome}). precheck = tool "
             "da chiamare prima (se non trova niente la routine non parte). deliver: hermes (notifica) o recap.",
             "POST", "/api/routines", "Nuova routine", required=["title", "instruction"],
             params={"title": s, "instruction": {"type": "string", "description": "cosa fare, in parole"},
                     "recurrence": {"type": "string", "description": "RRULE, es. FREQ=DAILY;BYHOUR=8;BYMINUTE=0"},
                     "start_at": s, "precheck": {"type": "object"}, "on": {"type": "object"},
                     "deliver": {"type": "string", "enum": ["hermes", "recap"]}},
             section="Routine", label="Nuova routine"),
        tool("routine_from_template", "Crea una routine da un modello (id da routine_templates) con i suoi campi.",
             "POST", "/api/routines/from-template/{template_id}", "Routine da modello", required=["template_id"],
             params={"template_id": s, "values": {"type": "object"}, "recurrence": s, "title": s},
             section="Routine"),
        tool("routine_run", "Esegue subito una routine (key da routine_list).", "POST", "/api/routines/{key}/run",
             "Esegui routine", required=["key"], params={"key": s}, section="Routine"),
        tool("special_list", "Compleanni, anniversari e date importanti, con quanti giorni mancano.",
             "GET", "/api/special", "Eventi speciali", section="Eventi speciali", label="Eventi speciali",
             prompt="Elenco breve per data: cosa, quando, tra quanti giorni."),
        tool("special_add",
             "Aggiunge un evento speciale chiesto dall'utente (compleanno, anniversario o altro), con quanti giorni "
             "prima avvisare. Compleanni e anniversari si ripetono ogni anno.",
             "POST", "/api/special", "Aggiungi evento speciale", required=["title", "day"],
             params={"title": s, "day": {"type": "string", "description": "AAAA-MM-GG"},
                     "kind": {"type": "string", "enum": list(special.KINDS)}, "lead_days": {"type": "integer"},
                     "person": s, "note": s}, section="Eventi speciali"),
        tool("special_remove", "Toglie un evento speciale (key da special_list).", "DELETE", "/api/special/{key}",
             "Togli evento speciale", required=["key"], params={"key": s}, section="Eventi speciali"),
        tool("special_propose",
             "Quando trovi una data importante (in una mail, in una conversazione, nella memoria) che l'utente non "
             "ha chiesto di salvare: proponila, l'utente conferma con un tocco.",
             "POST", "/api/special/propose", "Proponi evento speciale", required=["title", "day"],
             params={"title": s, "day": s, "kind": {"type": "string", "enum": list(special.KINDS)}, "person": s,
                     "evidence": {"type": "string", "description": "dove l'hai trovata, una riga"}},
             section="Eventi speciali"),
        tool("calendar_check",
             "Controlla i prossimi giorni del calendario: se due impegni si sovrappongono propone dove spostarne uno.",
             "POST", "/api/calendar/smart/check", "Controlla sovrapposizioni", params={"days": {"type": "integer"}},
             section="Calendario", label="Sovrapposizioni"),
        tool("presence_set",
             "Cambia a mano lo stato dell'assistente (es. focus, riposo, fuori) per un tempo (minuti) o finché "
             "l'utente lo toglie.", "POST", "/api/presence/manual", "Cambia stato", required=["state"],
             params={"state": s, "minutes": {"type": "number"}}, section="Stato", label="Cambia stato",
             group="sistema"),
        tool("presence_clear", "Toglie lo stato messo a mano: l'assistente torna a decidere da solo.",
             "DELETE", "/api/presence/manual", "Stato automatico", section="Stato", label="Stato automatico",
             group="sistema"),
        tool("presence_history", "Gli ultimi cambi di stato dell'assistente, con il motivo.",
             "GET", "/api/presence/history", "Storia dello stato", params={"limit": {"type": "integer"}},
             section="Stato", label="Storia stato", group="sistema",
             prompt="Elenco breve: quando, da che stato a quale, perché."),
    ]

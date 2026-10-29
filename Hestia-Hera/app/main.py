"""Hestia-Hera — important people («Persone», port 19025, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A4).

Data in Archive (``/api/people-store``), dates in the calendar as Chronos special events, notices through Hermes,
settings in Themis, the daily check in the agenda, tools for the assistant and Telegram over MCP.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common import recap
from hestia_common.agenda_client import job_rule
from hestia_common.display import action, display, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.module_kit import ModuleKit
from hestia_common.transfer import StoreSection, Transfer

from .core.service import People

API = "/api/people"
kit = ModuleKit("hera", port=19025, api=API, domain="people", title="Persone", store="people-store",
                when_to_use="persone importanti: compleanni, anniversari, gusti, idee regalo, quando sentirle",
                manual="Schede delle persone (people_list, people_get): relazione, date importanti (vanno nel "
                       "calendario con preavviso), cosa piace e non piace, idee regalo. Quando l'utente nomina un "
                       "regalo o un gusto di una persona salvalo (people_gift_idea, people_like). people_contact "
                       "segna che l'ha sentita.")
app = kit.app
people = People(kit.store, kit.settings.get, tz_name=kit.tz, hub=kit.hub)


# ── REST (WebUI plugin, Hermes actions, Chronos push) ────────────────────────
@app.get(API)
def list_people(q: str = ""):
    return {"items": people.list(q)}


@app.post(API)
def add_person(body: dict = Body(...)):
    return people.save(body)


@app.get(f"{API}/upcoming")
def upcoming(days: int = 30):
    return {"items": people.upcoming(days)}


@app.get(f"{API}/{{pid}}")
def get_person(pid: str):
    return people.view(people.find(pid))


@app.put(f"{API}/{{pid}}")
def update_person(pid: str, body: dict = Body(...)):
    return people.save(body, pid)


@app.delete(f"{API}/{{pid}}")
def delete_person(pid: str):
    return people.delete(pid)


@app.post(f"{API}/{{pid}}/contact")
def contact(pid: str, body: dict = Body(default={})):
    return people.contact(pid, str(body.get("note") or ""), str(body.get("date") or ""))


@app.post(f"{API}/moment")
def special_moment(body: dict = Body(...)):
    """Chronos ``special_moment`` (capability ``special_moment_endpoint``)."""
    return people.moment(body)


@app.post(f"{API}/daily")
def daily():
    """Agenda job ``hera.daily``."""
    return people.daily()


app.include_router(recap.recap_router("hera", lambda d, n: recap.piece("hera", "Persone", icon="user", order=25,
                                                                       **people.recap(d, n)),
                                      today=people.today))


# ── tools ────────────────────────────────────────────────────────────────────
def _card(p: dict) -> dict:
    lines = [f"{d['label']}: {d['day'][-5:][3:]}/{d['day'][-5:][:2]} (tra {d['in_days']} giorni)" for d in p["dates"]]
    if p.get("likes"):
        lines.append("Piace: " + ", ".join(p["likes"][:8]))
    if p.get("dislikes"):
        lines.append("Non piace: " + ", ".join(p["dislikes"][:8]))
    if p.get("gift_ideas"):
        lines.append("Idee regalo: " + "; ".join(g["text"] for g in p["gift_ideas"][:6]))
    if p.get("last_contact"):
        lines.append(f"Sentita l'ultima volta: {p['last_contact']}")
    return display(p["name"], subtitle=p.get("relation") or "", lines=lines,
                   actions=[action("Idea regalo", "people_gift_idea", {"person": p["id"]}),
                            action("L'ho sentita", "people_contact", {"person": p["id"]}, style="primary")])


def _list(query: str = "") -> dict:
    items = people.list(query)
    return {"count": len(items), "items": [{"id": p["id"], "name": p["name"], "relation": p.get("relation")}
                                           for p in items],
            "display": display("Persone", items=[item(p["name"], [p.get("relation") or ""]) for p in items[:30]],
                               lines=[] if items else ["Nessuna persona salvata."],
                               actions=[action("Aggiungi", "people_add", style="primary")])}


def _get(person: str) -> dict:
    p = people.view(people.find(person))
    return {**p, "display": _card(p)}


def _add(name: str, relation: str = "", birthday: str = "", likes: list | None = None, notes: str = "",
         contact_every_days: int | None = None) -> dict:
    p = people.save({"name": name, "relation": relation or "altro", "birthday": birthday, "likes": likes or [],
                     "notes": notes, "contact_every_days": contact_every_days})
    return {"saved": True, "id": p["id"], "name": p["name"], "undo": undo("people_delete", person=p["id"]),
            "display": _card(p)}


def _update(person: str, relation: str = "", birthday: str = "", notes: str = "", contact_every_days: int | None = None,
            date_label: str = "", date_day: str = "") -> dict:
    body = {k: v for k, v in {"relation": relation, "birthday": birthday, "notes": notes,
                              "contact_every_days": contact_every_days}.items() if v}
    if date_label and date_day:
        body["dates"] = [{"label": date_label, "day": date_day, "kind": "anniversary"
                          if "anniversario" in date_label.casefold() else "custom"}]
    p = people.save(body, people.find(person)["id"])
    return {"saved": True, "display": _card(p)}


S, I, L = {"type": "string"}, {"type": "integer"}, {"type": "array", "items": {"type": "string"}}
P = {"type": "string", "description": "nome o id della persona"}
G = "persone"
kit.tools([
    MCPTool(name="people_list", description="Le persone importanti salvate (query = parte del nome o relazione).",
            parameters={"type": "object", "properties": {"query": S}}, handler=_list, title="Persone",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Persone", "primary": 1}),
    MCPTool(name="people_get", description="Scheda di una persona: date, gusti, idee regalo, ultimo contatto.",
            parameters={"type": "object", "properties": {"person": P}, "required": ["person"]}, handler=_get,
            title="Scheda persona", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Persone"}),
    MCPTool(name="people_add", description="Aggiungi una persona. relation: partner|famiglia|amico|collega|altro; "
            "birthday GG/MM o AAAA-MM-GG (va nel calendario con preavviso).",
            parameters={"type": "object", "properties": {"name": S, "relation": {"type": "string", "enum": [
                "partner", "famiglia", "amico", "collega", "altro"]}, "birthday": S, "likes": L, "notes": S,
                "contact_every_days": I}, "required": ["name"]},
            handler=_add, title="Aggiungi persona", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Persone", "primary": 2}),
    MCPTool(name="people_update", description="Modifica una persona; date_label + date_day aggiungono una data "
            "(es. «Anniversario» 14/02).",
            parameters={"type": "object", "properties": {"person": P, "relation": S, "birthday": S, "notes": S,
                                                         "contact_every_days": I, "date_label": S, "date_day": S},
                        "required": ["person"]},
            handler=_update, title="Modifica persona", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Persone"}),
    MCPTool(name="people_delete", description="Elimina la scheda di una persona (e le sue date dal calendario).",
            parameters={"type": "object", "properties": {"person": P}, "required": ["person"]},
            handler=lambda person: people.delete(person), title="Elimina persona", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Persone"}),
    MCPTool(name="people_gift_idea", description="Salva un'idea regalo per una persona (anche detta di passaggio "
            "in chat: «a Anna piacerebbe…»).",
            parameters={"type": "object", "properties": {"person": P, "idea": S}, "required": ["person", "idea"]},
            handler=lambda person, idea: {"saved": True, **_short(people.gift_idea(person, idea))},
            title="Idea regalo", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Regali", "primary": 3}),
    MCPTool(name="people_like", description="Salva un gusto (o con dislike=true qualcosa che non piace).",
            parameters={"type": "object", "properties": {"person": P, "text": S, "dislike": {"type": "boolean"}},
                        "required": ["person", "text"]},
            handler=lambda person, text, dislike=False: {"saved": True, **_short(people.like(person, text, dislike))},
            title="Gusto di una persona", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Persone"}),
    MCPTool(name="people_contact", description="Segna che l'utente ha sentito/visto una persona (note facoltative).",
            parameters={"type": "object", "properties": {"person": P, "note": S}, "required": ["person"]},
            handler=lambda person, note="": {"saved": True, **_short(people.contact(person, note))},
            title="L'ho sentita", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Persone"}),
    MCPTool(name="people_upcoming", description="Compleanni e date importanti dei prossimi giorni (days, default 30) "
            "con le idee regalo.",
            parameters={"type": "object", "properties": {"days": I}},
            handler=lambda days=30: {"items": people.upcoming(days),
                                     "display": display("Prossime date", items=[
                                         item(f"{u['label']} di {u['person']}", [u["next"][8:10] + "/" + u["next"][5:7],
                                                                                f"tra {u['in_days']} g"])
                                         for u in people.upcoming(days)[:20]])},
            title="Prossime date", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Regali", "primary": 4}),
], prefix="people_")


def _short(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"]}


transfer = Transfer("hera", kit.hub, sections=[
    StoreSection("persone", "Persone", kit.store, ["person"], icon="user", title=lambda r: r["data"].get("name", "")),
    StoreSection("contatti", "Contatti", kit.store, ["interaction"], icon="list", depends_on=["persone"]),
])
app.include_router(transfer.router())
kit.caps.update({"special_moment_endpoint": f"{API}/moment", **recap.capabilities()})
kit.capabilities(transfer.capabilities)
kit.agenda_rules(lambda: [job_rule("hera.daily", "Persone: chi sentire", service="hera", path=f"{API}/daily",
                                   recurrence="FREQ=DAILY", start_at="2026-01-01T18:00:00", tz=kit.tz,
                                   description="Un avviso per chi non senti da più del tempo che hai scelto.")])
kit.on_warm(lambda: [people.sync_calendar(p) for p in people.store.items("person")])
kit.finish()

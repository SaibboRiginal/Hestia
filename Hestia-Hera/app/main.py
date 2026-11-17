"""Hestia-Hera — important people («People», port 19025, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A4).

Data in Archive (``/api/people-store``), dates in the calendar as Chronos special events, notices through Hermes,
settings in Themis, the daily check in the agenda, tools for the assistant and Telegram over MCP.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common import recap
from hestia_common.agenda_client import job_rule
from hestia_common.display import action, display, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.module_kit import ModuleKit
from hestia_common.plugin_client import page, widget
from hestia_common.transfer import StoreSection, Transfer

from .core.service import People

API = "/api/people"
kit = ModuleKit("hera", port=19025, api=API, domain="people", title="People", store="people-store",
                when_to_use="important people: birthdays, anniversaries, tastes, gift ideas, when to reach out",
                manual="People cards (people_list, people_get): relationship, important dates (go to the calendar with notice), likes and dislikes, gift ideas. When the user mentions a gift or a taste of a person save it (people_gift_idea, people_like). people_contact marks that they were in touch.")
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


@app.post(f"{API}/{{pid}}/gift")
def add_gift(pid: str, body: dict = Body(...)):
    return people.gift_idea(pid, str(body.get("idea") or ""), source="webui")


@app.post(f"{API}/{{pid}}/gift/{{gid}}/done")
def gift_done(pid: str, gid: str):
    return people.gift_done(pid, gid)


@app.post(f"{API}/{{pid}}/like")
def add_like(pid: str, body: dict = Body(...)):
    return people.like(pid, str(body.get("text") or ""), bool(body.get("dislike")))


@app.post(f"{API}/moment")
def special_moment(body: dict = Body(...)):
    """Chronos ``special_moment`` (capability ``special_moment_endpoint``)."""
    return people.moment(body)


@app.post(f"{API}/daily")
def daily():
    """Agenda job ``hera.daily``."""
    return people.daily()


app.include_router(recap.recap_router("hera", lambda d, n: recap.piece("hera", tr("People"), icon="user", order=25,
                                                                       **people.recap(d, n)),
                                      today=people.today))


# ── tools ────────────────────────────────────────────────────────────────────
def _card(p: dict) -> dict:
    lines = [tr("{0}: {1}/{2} (in {3} days)", d['label'], d['day'][-5:][3:], d['day'][-5:][:2], d['in_days']) for d in p["dates"]]
    if p.get("likes"):
        lines.append(tr("Likes: ") + ", ".join(p["likes"][:8]))
    if p.get("dislikes"):
        lines.append(tr("Dislikes: ") + ", ".join(p["dislikes"][:8]))
    if p.get("gift_ideas"):
        lines.append(tr("Gift ideas: ") + "; ".join(g["text"] for g in p["gift_ideas"][:6]))
    if p.get("last_contact"):
        lines.append(tr("Last talked: {0}", p['last_contact']))
    return display(p["name"], subtitle=p.get("relation") or "", lines=lines,
                   actions=[action(tr("Gift idea"), "people_gift_idea", {"person": p["id"]}),
                            action(tr("I talked to them"), "people_contact", {"person": p["id"]}, style="primary")])


def _list(query: str = "") -> dict:
    items = people.list(query)
    return {"count": len(items), "items": [{"id": p["id"], "name": p["name"], "relation": p.get("relation")}
                                           for p in items],
            "display": display(tr("People"), items=[item(p["name"], [p.get("relation") or ""]) for p in items[:30]],
                               lines=[] if items else [tr("No person saved.")],
                               actions=[action(tr("Add"), "people_add", style="primary")])}


def _get(person: str) -> dict:
    p = people.view(people.find(person))
    return {**p, "display": _card(p)}


def _add(name: str, relation: str = "", birthday: str = "", likes: list | None = None, notes: str = "",
         contact_every_days: int | None = None) -> dict:
    p = people.save({"name": name, "relation": relation or "other", "birthday": birthday, "likes": likes or [],
                     "notes": notes, "contact_every_days": contact_every_days})
    return {"saved": True, "id": p["id"], "name": p["name"], "undo": undo("people_delete", person=p["id"]),
            "display": _card(p)}


def _update(person: str, relation: str = "", birthday: str = "", notes: str = "", contact_every_days: int | None = None,
            date_label: str = "", date_day: str = "") -> dict:
    body = {k: v for k, v in {"relation": relation, "birthday": birthday, "notes": notes,
                              "contact_every_days": contact_every_days}.items() if v}
    if date_label and date_day:
        body["dates"] = [{"label": date_label, "day": date_day, "kind": "anniversary"
                          if "anniversary" in date_label.casefold() else "custom"}]
    p = people.save(body, people.find(person)["id"])
    return {"saved": True, "display": _card(p)}


S, I, L = {"type": "string"}, {"type": "integer"}, {"type": "array", "items": {"type": "string"}}
P = {"type": "string", "description": "person's name or id"}
G = "people"
kit.tools([
    MCPTool(name="people_list", description="The important people saved (query = part of the name or relation).",
            parameters={"type": "object", "properties": {"query": S}}, handler=_list, title="People",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "People", "primary": 1}),
    MCPTool(name="people_get", description="A person's card: dates, likes, gift ideas, last contact.",
            parameters={"type": "object", "properties": {"person": P}, "required": ["person"]}, handler=_get,
            title="Person card", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "People"}),
    MCPTool(name="people_add", description=("Add a person. relation: partner|family|friend|colleague|other; birthday DD/MM or YYYY-MM-DD "
                                            "(goes into the calendar with a reminder)."),
            parameters={"type": "object", "properties": {"name": S, "relation": {"type": "string", "enum": [
                "partner", "family", "friend", "colleague", "other"]}, "birthday": S, "likes": L, "notes": S,
                "contact_every_days": I}, "required": ["name"]},
            handler=_add, title="Add person", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "People", "primary": 2}),
    MCPTool(name="people_update", description="Edit a person; date_label + date_day add a date (e.g. «Anniversary» 14/02).",
            parameters={"type": "object", "properties": {"person": P, "relation": S, "birthday": S, "notes": S,
                                                         "contact_every_days": I, "date_label": S, "date_day": S},
                        "required": ["person"]},
            handler=_update, title="Edit person", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "People"}),
    MCPTool(name="people_delete", description="Delete a person's card (and their dates from the calendar).",
            parameters={"type": "object", "properties": {"person": P}, "required": ["person"]},
            handler=lambda person: people.delete(person), title="Delete person", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "People"}),
    MCPTool(name="people_gift_idea", description="Save a gift idea for a person (also said in passing in chat: «Anna would like…»).",
            parameters={"type": "object", "properties": {"person": P, "idea": S}, "required": ["person", "idea"]},
            handler=lambda person, idea: {"saved": True, **_short(people.gift_idea(person, idea))},
            title="Gift idea", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Gifts", "primary": 3}),
    MCPTool(name="people_like", description="Save a like (or with dislike=true something they do not like).",
            parameters={"type": "object", "properties": {"person": P, "text": S, "dislike": {"type": "boolean"}},
                        "required": ["person", "text"]},
            handler=lambda person, text, dislike=False: {"saved": True, **_short(people.like(person, text, dislike))},
            title="A person's taste", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "People"}),
    MCPTool(name="people_contact", description="Mark that the user heard from/saw a person (optional notes).",
            parameters={"type": "object", "properties": {"person": P, "note": S}, "required": ["person"]},
            handler=lambda person, note="": {"saved": True, **_short(people.contact(person, note))},
            title="I talked to them", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "People"}),
    MCPTool(name="people_upcoming", description="Birthdays and important dates of the next days (days, default 30) with gift ideas.",
            parameters={"type": "object", "properties": {"days": I}},
            handler=lambda days=30: {"items": people.upcoming(days),
                                     "display": display(tr("Upcoming dates"), items=[
                                         item(tr("{0} of {1}", u['label'], u['person']), [u["next"][8:10] + "/" + u["next"][5:7],
                                                                                tr("in {0} d", u['in_days'])])
                                         for u in people.upcoming(days)[:20]])},
            title="Upcoming dates", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Gifts", "primary": 4}),
], prefix="people_")


def _short(p: dict) -> dict:
    return {"id": p["id"], "name": p["name"]}


transfer = Transfer("hera", kit.hub, sections=[
    StoreSection("people", "People", kit.store, ["person"], icon="user", title=lambda r: r["data"].get("name", "")),
    StoreSection("contacts", "Contacts", kit.store, ["interaction"], icon="list", depends_on=["people"]),
])
app.include_router(transfer.router())
kit.caps.update({"special_moment_endpoint": f"{API}/moment", **recap.capabilities()})
kit.capabilities(transfer.capabilities)
kit.agenda_rules(lambda: [job_rule("hera.daily", tr("People: who to call"), service="hera", path=f"{API}/daily",
                                   recurrence="FREQ=DAILY", start_at="2026-01-01T18:00:00", tz=kit.tz,
                                   description="A notice for whoever you haven't heard from for longer than the time you chose.")])
kit.on_warm(lambda: [people.sync_calendar(p) for p in people.store.items("person")])
kit.webui(icon="user", color="pink", description="The important people: dates in the calendar, tastes, gift ideas.",
          pages=[page("people", "People", element="hera-people", icon="user", order=90,
                      help="Who matters to you: birthdays and dates (they go in the calendar with a notice), tastes, gift ideas the assistant notes from the chat, when to hear from them."),
                 page("persona/:id", "Persona", element="hera-person", detail=True, parent="people")],
          widgets=[widget("upcoming", "Upcoming dates", element="hera-soon-widget", sizes=["s", "m", "l"], size="m",
                          auto=True, open_page="people", icon="heart")])
kit.finish()

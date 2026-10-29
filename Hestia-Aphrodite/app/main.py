"""Hestia-Aphrodite — how the clients look («Aspetto», port 19023, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A2).

Profiles, pets and per-client choices in Archive (``/api/appearance-store``); today's special moments pushed by the
calendar (capability ``special_moment_endpoint``); pictures asked to the image module with a callback; clients read
``GET /api/appearance/now?client=``; tools for the assistant and Telegram over MCP.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import Body

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common.display import action, display, file, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.module_kit import ModuleKit
from hestia_common.transfer import StoreSection, Transfer

from .core.service import CLIENTS, EFFECTS, Appearance

API = "/api/appearance"
kit = ModuleKit("aphrodite", port=19023, api=API, domain="appearance", title="Aspetto", store="appearance-store",
                when_to_use="aspetto del sito: temi delle feste e delle stagioni, effetti, animaletto da compagnia",
                manual="L'aspetto cambia da solo (compleanno, feste, stagioni): aspetto_adesso dice cosa si vede e "
                       "perché. aspetto_scelta spegne i temi (torna lo standard) o sceglie l'animaletto. "
                       "aspetto_animale crea un animaletto; aspetto_genera chiede le sue immagini o lo sfondo.")
app = kit.app
look = Appearance(kit.store, kit.hub, tz_name=kit.tz)


@app.get(f"{API}/now")
def now(client: str = "webui"):
    """What a client shows now: the only call clients make."""
    return look.now(client)


@app.get(f"{API}/profiles")
def profiles():
    return {"items": look.profiles(), "effects": list(EFFECTS)}


@app.post(f"{API}/profiles")
def add_profile(body: dict = Body(...)):
    return look.save_profile(body)


@app.put(f"{API}/profiles/{{key}}")
def update_profile(key: str, body: dict = Body(...)):
    return look.save_profile(body, key)


@app.get(f"{API}/pets")
def pets():
    return {"items": look.pets()}


@app.post(f"{API}/pets")
def add_pet(body: dict = Body(...)):
    return look.save_pet(body)


@app.put(f"{API}/pets/{{pid}}")
def update_pet(pid: str, body: dict = Body(...)):
    return look.save_pet(body, pid)


@app.delete(f"{API}/pets/{{pid}}")
def delete_pet(pid: str):
    return look.delete_pet(pid)


@app.get(f"{API}/choice/{{client}}")
def get_choice(client: str):
    return look.choice(client)


@app.put(f"{API}/choice/{{client}}")
def put_choice(client: str, body: dict = Body(...)):
    return look.set_choice(client, auto=body.get("auto"), pet=body.get("pet"))


@app.get(f"{API}/upcoming")
def upcoming(days: int = 60):
    return {"items": look.upcoming(days)}


@app.post(f"{API}/moment")
def special_moment(body: dict = Body(...)):
    """Calendar ``special_moment`` (capability ``special_moment_endpoint``)."""
    return look.moment(body)


@app.post(f"{API}/images/done")
def image_done(body: dict = Body(...)):
    """Push from the image module when a picture asked by ``generate`` is ready."""
    return look.image_done(body)


# ── tools ────────────────────────────────────────────────────────────────────
def _now(client: str = "webui") -> dict:
    n = look.now(client)
    p = n["profile"]
    lines = [f"Tema: {p['name']}" + ("" if n["auto"] else " (temi spenti)"), f"Perché: {n['why']}"]
    if n["pet"]:
        lines.append(f"Animaletto: {n['pet']['name']}")
    files = [file(p["background"], "sfondo.png", "image/png")] if p.get("background") else []
    return {**n, "display": display("Aspetto adesso", lines=lines, files=files, actions=[
        action("Spegni i temi" if n["auto"] else "Riaccendi i temi", "aspetto_scelta",
               {"client": client, "auto": not n["auto"]}),
        action("Prossimi temi", "aspetto_prossimi")])}


def _choice(client: str = "webui", auto: bool | None = None, pet: str | None = None) -> dict:
    before = look.choice(client)
    out = look.set_choice(client, auto=auto, pet=pet)
    return {"saved": True, **out, "undo": undo("aspetto_scelta", client=client, auto=before["auto"], pet=before["pet"])}


def _pet(name: str, species: str = "gatto", look_: str = "") -> dict:
    p = look.save_pet({"name": name, "species": species, "look": look_})
    gen = look.generate("pet", p["id"])
    return {"saved": True, "id": p["id"], "name": p["name"], "images_asked": gen["asked"],
            "display": display(p["name"], subtitle=p["species"], lines=["Sto preparando le sue immagini: arrivano da "
                                                                        "sole quando sono pronte."],
                               actions=[action("Usalo sul sito", "aspetto_scelta", {"client": "webui", "pet": p["id"]},
                                               style="primary")])}


S, B = {"type": "string"}, {"type": "boolean"}
CL = {"type": "string", "enum": list(CLIENTS), "description": "dove (default webui)"}
G = "aspetto"
kit.tools([
    MCPTool(name="aspetto_adesso", description="Che aspetto ha adesso il sito e perché (festa, stagione, compleanno).",
            parameters={"type": "object", "properties": {"client": CL}}, handler=_now, title="Aspetto adesso",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Aspetto", "primary": 3}),
    MCPTool(name="aspetto_scelta", description="Per un client: auto=false spegne i temi (aspetto standard), true li "
            "riaccende; pet = id o nome dell'animaletto, vuoto per nessuno.",
            parameters={"type": "object", "properties": {"client": CL, "auto": B, "pet": S}},
            handler=_choice, title="Scegli aspetto", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Aspetto", "primary": 4}),
    MCPTool(name="aspetto_prossimi", description="I temi dei prossimi giorni (days, default 60).",
            parameters={"type": "object", "properties": {"days": {"type": "integer"}}},
            handler=lambda days=60: (lambda rows: {"items": rows, "display": display("Prossimi temi", items=[
                item(r["why"], [r["date"][8:10] + "/" + r["date"][5:7]]) for r in rows[:15]])})(look.upcoming(days)),
            title="Prossimi temi", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Aspetto"}),
    MCPTool(name="aspetto_animale", description="Crea un animaletto da compagnia (name, species, look = com'è fatto) "
            "e ne chiede le immagini.",
            parameters={"type": "object", "properties": {"name": S, "species": S, "look": S}, "required": ["name"]},
            handler=lambda name, species="gatto", look="": _pet(name, species, look), title="Nuovo animaletto",
            method="POST", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Aspetto"}),
    MCPTool(name="aspetto_animali", description="Gli animaletti creati.", parameters={"type": "object", "properties": {}},
            handler=lambda: (lambda rows: {"items": rows, "display": display("Animaletti", items=[
                item(p["name"], [p["species"], f"{len(p.get('images') or {})}/3 immagini"]) for p in rows],
                lines=[] if rows else ["Nessun animaletto."])})(look.pets()),
            title="Animaletti", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Aspetto"}),
    MCPTool(name="aspetto_genera", description="Chiedi di nuovo le immagini: target profile (sfondo) o pet; ref = "
            "chiave del profilo o id/nome dell'animaletto.",
            parameters={"type": "object", "properties": {"target": {"type": "string", "enum": ["profile", "pet"]},
                                                         "ref": S}, "required": ["target", "ref"]},
            handler=lambda target, ref: look.generate(target, look.pet(ref)["id"] if target == "pet" else ref),
            title="Rigenera immagini", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Aspetto"}),
], prefix="aspetto_")

transfer = Transfer("aphrodite", kit.hub, sections=[
    StoreSection("aspetto", "Aspetto", kit.store, ["profile", "pet", "choice"], icon="palette",
                 title=lambda r: r["data"].get("name", r["id"]), file_fields=["background"]),
])
app.include_router(transfer.router())
kit.caps.update({"special_moment_endpoint": f"{API}/moment"})
kit.capabilities(transfer.capabilities)
kit.finish()

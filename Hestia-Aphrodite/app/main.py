"""Hestia-Aphrodite — how the clients look («Aspetto», port 19023, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A2).

Profiles, pets and per-client choices in Archive (``/api/appearance-store``); today's special moments pushed by the
calendar (capability ``special_moment_endpoint``); pictures asked to the image module with a callback; clients read
``GET /api/appearance/now?client=``; tools for the assistant and Telegram over MCP.
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

from hestia_common.display import action, display, file, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.module_kit import Invalid, ModuleKit, NotFound
from hestia_common.plugin_client import page
from hestia_common.transfer import StoreSection, Transfer

from .core.service import CLIENTS, EFFECTS, POSES, Appearance

API = "/api/appearance"
kit = ModuleKit("aphrodite", port=19023, api=API, domain="appearance", title="Look", store="appearance-store",
                when_to_use="site look: holiday and season themes, effects, companion pet",
                manual="The look changes by itself (birthday, holidays, seasons): aspetto_adesso says what is shown and why. aspetto_scelta turns themes off (back to standard) or picks the pet. aspetto_animale creates a pet; aspetto_genera asks for its images or the background.")
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


@app.get(f"{API}/image/{{bid}}")
def image(bid: str):
    """A background or pet picture as ``{mime, data_b64}`` (WebUI ``host.image``); only blobs this module uses."""
    used = {p.get("background") for p in look.profiles()} | {
        b for p in look.pets() for b in (p.get("images") or {}).values()}
    if not bid or bid not in used:
        raise NotFound(tr("image not found"))
    blob = kit.hub.ok("archive", "GET", f"api/blobs/{bid}/base64", timeout=30) or {}
    return {"mime": blob.get("mime") or "image/png", "data_b64": blob.get("data_b64") or ""}


@app.post(f"{API}/pets/{{pid}}/image/{{pose}}")
def upload_pet_image(pid: str, pose: str, body: dict = Body(...)):
    """A picture of the pet chosen by the owner (wins over a generated one)."""
    if pose not in POSES or not body.get("data_b64"):
        raise Invalid("posa: " + ", ".join(POSES) + " e l'immagine")
    look.pet(pid)
    out = kit.hub.ok("archive", "POST", "api/blobs", body={"owner_module": "aphrodite", "content_type": body.get("mime") or
                                                           "image/png", "data_base64": body["data_b64"],
                                                           "meta": {"pet": pid, "pose": pose}}, timeout=30) or {}
    return look.save_pet({f"image_{pose}": out.get("blob_id")}, pid)


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
    lines = [tr("Theme: {0}", p['name']) + ("" if n["auto"] else tr(" (themes off)")), tr("Why: {0}", n['why'])]
    if n["pet"]:
        lines.append(tr("Pet: {0}", n['pet']['name']))
    files = [file(p["background"], "sfondo.png", "image/png")] if p.get("background") else []
    return {**n, "display": display(tr("Look now"), lines=lines, files=files, actions=[
        action(tr("Turn themes off") if n["auto"] else tr("Turn themes back on"), "aspetto_scelta",
               {"client": client, "auto": not n["auto"]}),
        action(tr("Upcoming themes"), "aspetto_prossimi")])}


def _choice(client: str = "webui", auto: bool | None = None, pet: str | None = None) -> dict:
    before = look.choice(client)
    out = look.set_choice(client, auto=auto, pet=pet)
    return {"saved": True, **out, "undo": undo("aspetto_scelta", client=client, auto=before["auto"], pet=before["pet"])}


def _pet(name: str, species: str = "gatto", look_: str = "") -> dict:
    p = look.save_pet({"name": name, "species": species, "look": look_})
    gen = look.generate("pet", p["id"])
    return {"saved": True, "id": p["id"], "name": p["name"], "images_asked": gen["asked"],
            "display": display(p["name"], subtitle=p["species"], lines=[tr("I'm preparing its images: they arrive by themselves when ready.")],
                               actions=[action(tr("Use it on the site"), "aspetto_scelta", {"client": "webui", "pet": p["id"]},
                                               style="primary")])}


S, B = {"type": "string"}, {"type": "boolean"}
CL = {"type": "string", "enum": list(CLIENTS), "description": "where (default webui)"}
G = "aspetto"
kit.tools([
    MCPTool(name="aspetto_adesso", description="How the site looks now and why (holiday, season, birthday).",
            parameters={"type": "object", "properties": {"client": CL}}, handler=_now, title="Look now",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Look", "primary": 3}),
    MCPTool(name="aspetto_scelta", description=("For a client: auto=false turns the themes off (standard look), true turns them back on; pet = "
                                                "id or name of the pet, empty for none."),
            parameters={"type": "object", "properties": {"client": CL, "auto": B, "pet": S}},
            handler=_choice, title="Choose look", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Look", "primary": 4}),
    MCPTool(name="aspetto_prossimi", description="The themes of the next days (days, default 60).",
            parameters={"type": "object", "properties": {"days": {"type": "integer"}}},
            handler=lambda days=60: (lambda rows: {"items": rows, "display": display(tr("Upcoming themes"), items=[
                item(r["why"], [r["date"][8:10] + "/" + r["date"][5:7]]) for r in rows[:15]])})(look.upcoming(days)),
            title="Upcoming themes", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Look"}),
    MCPTool(name="aspetto_animale", description="Create a pet companion (name, species, look = what it looks like) and ask for its images.",
            parameters={"type": "object", "properties": {"name": S, "species": S, "look": S}, "required": ["name"]},
            handler=lambda name, species="gatto", look="": _pet(name, species, look), title="New pet",
            method="POST", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Look"}),
    MCPTool(name="aspetto_animali", description="The pets created.", parameters={"type": "object", "properties": {}},
            handler=lambda: (lambda rows: {"items": rows, "display": display(tr("Pets"), items=[
                item(p["name"], [p["species"], f"{len(p.get('images') or {})}/3 immagini"]) for p in rows],
                lines=[] if rows else [tr("No pet.")])})(look.pets()),
            title="Pets", clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Look"}),
    MCPTool(name="aspetto_genera", description=("Ask for the images again: target profile (background) or pet; ref = profile key or the pet's "
                                                "id/name."),
            parameters={"type": "object", "properties": {"target": {"type": "string", "enum": ["profile", "pet"]},
                                                         "ref": S}, "required": ["target", "ref"]},
            handler=lambda target, ref: look.generate(target, look.pet(ref)["id"] if target == "pet" else ref),
            title="Regenerate images", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Look"}),
], prefix="aspetto_")

transfer = Transfer("aphrodite", kit.hub, sections=[
    StoreSection("aspetto", "Look", kit.store, ["profile", "pet", "choice"], icon="palette",
                 title=lambda r: r["data"].get("name", r["id"]), file_fields=["background"]),
])
app.include_router(transfer.router())
kit.caps.update({"special_moment_endpoint": f"{API}/moment"})
kit.capabilities(transfer.capabilities)
kit.webui(icon="palette", color="pink", description="Holiday, season and special-day themes, a little pet.",
          pages=[page("aspetto", "Look", element="aphrodite-look", icon="palette", order=220,
                      help="The site changes by itself with holidays, seasons and your special days: here you see what is on now and why, turn themes off, choose and create the little pet, edit the profiles.")])
kit.finish()

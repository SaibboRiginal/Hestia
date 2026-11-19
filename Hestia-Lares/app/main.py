"""Hestia-Lares — the house on Home Assistant («Home», port 19024, dossier docs/work/2026-10-24-whole-cindy-brainstorm W5 A3).

Home Assistant is reached only from here (``LARES_HA_URL`` / ``LARES_HA_TOKEN`` in env). State changes arrive by
push on the HA websocket; favourites in Archive (``/api/home-store``); the chosen person entity → presence signal
``home.present``; tools for the assistant and Telegram over MCP.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from fastapi import Body
from hestia_common.i18n import t as tr  # fixed texts in the owner's language

try:
    import hestia_common  # noqa: F401
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Hestia-Shared"))

from hestia_common.display import action, display, item
from hestia_common.mcp_helpers import MCPTool, undo
from hestia_common.module_kit import ModuleKit
from hestia_common.plugin_client import page, quick_action, widget
from hestia_common.presence_client import PresenceClient
from hestia_common.settings_client import setting
from hestia_common.transfer import StoreSection, Transfer

from .core.ha import HomeAssistant
from .core.service import COMMANDS, DOMAINS, LABELS, Home

API = "/api/home"
kit = ModuleKit("lares", port=19024, api=API, domain="home", title="Home", store="home-store",
                when_to_use="home: lights, plugs, blinds, climate, sensors, scenes, who is home",
                manual="The home (home_status): lights on, temperatures, open doors. home_command turns on/off/opens a device by name; home_scene runs a scene; home_devices lists by type; home_favorite saves a quick action.")
app = kit.app
kit.settings.declare([
    setting("lares.person", "You in Home Assistant", "enum", "", group="Home", order=0,
            options_source=f"{API}/persons/options",
            help="The Home Assistant person that is you: when you leave or come back, the assistant knows if you are home."),
])
ha = HomeAssistant(os.getenv("LARES_HA_URL", ""), os.getenv("LARES_HA_TOKEN", ""))
home = Home(kit.store, ha, kit.settings.get, presence=PresenceClient("lares", kit.hub_url))
kit.health_extra = lambda: {"configured": ha.configured, "connected": home.connected}


def _listen() -> None:
    ha.listen(lambda new: home.changed(new), on_connect=home.load)


# ── REST (WebUI plugin) ──────────────────────────────────────────────────────
@app.get(f"{API}/status")
def status():
    return home.status()


@app.get(f"{API}/persons/options")
def persons_options():
    """Options of «Tu in Home Assistant» (Themis ``options_source``)."""
    try:
        rows = home.list("person")
    except Exception:
        rows = []
    return {"options": [{"value": "", "label": tr("f::None")}] + [{"value": e["id"], "label": e["name"]} for e in rows]}


@app.get(f"{API}/entities")
def entities(domain: str = "", q: str = ""):
    return {"items": home.list(domain, q), "domains": {d: LABELS[d] for d in DOMAINS}}


@app.post(f"{API}/entities/{{entity_id}}/{{command}}")
def command(entity_id: str, command: str, body: dict = Body(default={})):
    return home.command(entity_id, command, body.get("value"))


@app.get(f"{API}/favorites")
def favorites():
    return {"items": home.favorites()}


@app.post(f"{API}/favorites")
def add_favorite(body: dict = Body(...)):
    return home.add_favorite(body.get("entity", ""), body.get("label", ""), body.get("room", ""),
                             body.get("command", "toggle"))


@app.get(f"{API}/quick")
def quick_chips():
    """Chips of the quick action «Home» (Home strip, Ctrl+K): the saved quick actions."""
    try:
        return [{"id": f["id"], "label": f["label"], "icon": "home", "hint": f.get("room") or ""}
                for f in home.favorites()]
    except Exception:
        return []


@app.post(f"{API}/favorites/{{fid}}/run")
def run_favorite(fid: str):
    return home.run_favorite(fid)


@app.delete(f"{API}/favorites/{{fid}}")
def delete_favorite(fid: str):
    return home.delete_favorite(fid)


# ── tools ────────────────────────────────────────────────────────────────────
def _status() -> dict:
    s = home.status()
    if not s["configured"]:
        return {**s, "display": display(tr("Home"), lines=[tr("The home is not linked yet.")])}
    if not s.get("connected") and s.get("error"):
        return {**s, "display": display(tr("Home"), lines=[s["error"]])}
    lines = [(tr("Lights on: ") + ", ".join(s["lights_on"][:8])) if s["lights_on"] else tr("All lights off")]
    if s["temperatures"]:
        lines.append(tr("Temperatures: ") + "; ".join(s["temperatures"]))
    if s["open"]:
        lines.append(tr("Open: ") + ", ".join(s["open"]))
    return {**s, "display": display(tr("Home"), lines=lines, actions=[
        action(f["label"], "home_favorite_run", {"favorite": f["id"]}) for f in s["favorites"][:6]])}


def _devices(domain: str = "", query: str = "") -> dict:
    rows = home.list(domain, query)
    return {"count": len(rows), "items": rows[:80], "display": display(
        LABELS.get(domain, "Devices"), items=[item(e["name"], [home.say(e)]) for e in rows[:30]],
        lines=[] if rows else [tr("No devices.")])}


def _command(device: str, command: str = "toggle", value: float | None = None) -> dict:
    out = home.command(device, command, value)
    back = {"on": "off", "off": "on", "open": "close", "close": "open", "lock": "unlock", "unlock": "lock",
            "toggle": "toggle"}[command]
    return {**out, "undo": undo("home_command", device=device, command=back)}


S, N = {"type": "string"}, {"type": "number"}
DEV = {"type": "string", "description": "device name or entity_id"}
G = "home"
kit.tools([
    MCPTool(name="home_status", description="How the house is now: lights on, temperatures, open doors/windows, quick actions.", parameters={"type": "object", "properties": {}}, handler=_status, title="Home now",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Home", "primary": 1}),
    MCPTool(name="home_devices", description="Devices of one type (domain: " + ", ".join(DOMAINS) + ").",
            parameters={"type": "object", "properties": {"domain": {"type": "string", "enum": list(DOMAINS)},
                                                         "query": S}},
            handler=_devices, title="Devices", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Home", "primary": 2}),
    MCPTool(name="home_command", description=("Command a device: command on|off|toggle|open|close|lock|unlock; value = brightness % for lights "
                                              "or degrees for climate."),
            parameters={"type": "object", "properties": {"device": DEV, "command": {"type": "string", "enum": list(
                COMMANDS)}, "value": N}, "required": ["device"]},
            handler=_command, title="f::Command", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Home", "primary": 3}),
    MCPTool(name="home_scene", description="Run a Home Assistant scene or action (by name).",
            parameters={"type": "object", "properties": {"scene": S}, "required": ["scene"]},
            handler=lambda scene: home.scene(scene), title="Scene", method="POST", clients=["telegram", "ui"],
            telegram_group=G, telegram={"section": "Scene", "primary": 4}),
    MCPTool(name="home_favorite", description="Save a quick action: device, label, room, command (default toggle).",
            parameters={"type": "object", "properties": {"device": DEV, "label": S, "room": S, "command": {
                "type": "string", "enum": list(COMMANDS)}}, "required": ["device"]},
            handler=lambda device, label="", room="", command="toggle": (lambda f: {
                "saved": True, **f, "undo": undo("home_favorite_delete", favorite=f["id"])})(
                home.add_favorite(device, label, room, command)),
            title="Quick action", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scene"}),
    MCPTool(name="home_favorite_run", description="Run a saved quick action.",
            parameters={"type": "object", "properties": {"favorite": S}, "required": ["favorite"]},
            handler=lambda favorite: home.run_favorite(favorite), title="Run quick action", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scene"}),
    MCPTool(name="home_favorite_delete", description="Delete a quick action.",
            parameters={"type": "object", "properties": {"favorite": S}, "required": ["favorite"]},
            handler=lambda favorite: home.delete_favorite(favorite), title="Delete quick action", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scene"}),
], prefix="home_")

transfer = Transfer("lares", kit.hub, sections=[
    StoreSection("favorites", "Quick actions", kit.store, ["favorite"], icon="zap",
                 title=lambda r: r["data"].get("label", "")),
])
app.include_router(transfer.router())
kit.capabilities(transfer.capabilities)
kit.on_warm(lambda: threading.Thread(target=_listen, daemon=True, name="lares-ha-ws").start())
kit.webui(icon="home", color="teal", description="The house on Home Assistant: lights, shutters, climate, scenes, quick actions.",
          pages=[page("home", "Home", element="lares-home", icon="home", order=230,
                      help="The house now, the quick actions and all Home Assistant devices by type.")],
          widgets=[widget("home", "Home", element="lares-widget", sizes=["s", "m", "l"], size="m", auto=True,
                          open_page="home", icon="home")],
          quick_actions=[quick_action("action", "Home", "POST", f"{API}/favorites/{{id}}/run", icon="home",
                                      group="Home", source=f"{API}/quick", order=230)])
kit.finish()

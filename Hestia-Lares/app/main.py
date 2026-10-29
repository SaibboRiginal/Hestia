"""Hestia-Lares — the house on Home Assistant («Casa», port 19024, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W5 A3).

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
kit = ModuleKit("lares", port=19024, api=API, domain="home", title="Casa", store="home-store",
                when_to_use="casa: luci, prese, tapparelle, clima, sensori, scene, chi è a casa",
                manual="La casa (casa_stato): luci accese, temperature, porte aperte. casa_comando accende/spegne/apre "
                       "un dispositivo per nome; casa_scena attiva una scena; casa_dispositivi elenca per tipo; "
                       "casa_preferito salva un'azione rapida.")
app = kit.app
kit.settings.declare([
    setting("lares.persona", "Tu in Home Assistant", "enum", "", group="Casa", order=0,
            options_source=f"{API}/persons/options",
            help="La persona di Home Assistant che sei tu: quando esci o rientri, l'assistente sa se sei a casa."),
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
    return {"options": [{"value": "", "label": "Nessuna"}] + [{"value": e["id"], "label": e["name"]} for e in rows]}


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
    """Chips of the quick action «Casa» (Home strip, Ctrl+K): the saved quick actions."""
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
        return {**s, "display": display("Casa", lines=["La casa non è ancora collegata."])}
    if not s.get("connected") and s.get("error"):
        return {**s, "display": display("Casa", lines=[s["error"]])}
    lines = [("Luci accese: " + ", ".join(s["lights_on"][:8])) if s["lights_on"] else "Tutte le luci spente"]
    if s["temperatures"]:
        lines.append("Temperature: " + "; ".join(s["temperatures"]))
    if s["open"]:
        lines.append("Aperte: " + ", ".join(s["open"]))
    return {**s, "display": display("Casa", lines=lines, actions=[
        action(f["label"], "casa_preferito_esegui", {"favorite": f["id"]}) for f in s["favorites"][:6]])}


def _devices(domain: str = "", query: str = "") -> dict:
    rows = home.list(domain, query)
    return {"count": len(rows), "items": rows[:80], "display": display(
        LABELS.get(domain, "Dispositivi"), items=[item(e["name"], [home.say(e)]) for e in rows[:30]],
        lines=[] if rows else ["Nessun dispositivo."])}


def _command(device: str, command: str = "toggle", value: float | None = None) -> dict:
    out = home.command(device, command, value)
    back = {"on": "off", "off": "on", "open": "close", "close": "open", "lock": "unlock", "unlock": "lock",
            "toggle": "toggle"}[command]
    return {**out, "undo": undo("casa_comando", device=device, command=back)}


S, N = {"type": "string"}, {"type": "number"}
DEV = {"type": "string", "description": "nome o entity_id del dispositivo"}
G = "casa"
kit.tools([
    MCPTool(name="casa_stato", description="Com'è la casa adesso: luci accese, temperature, porte/finestre aperte, "
            "azioni rapide.", parameters={"type": "object", "properties": {}}, handler=_status, title="Casa adesso",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Casa", "primary": 1}),
    MCPTool(name="casa_dispositivi", description="Dispositivi di un tipo (domain: " + ", ".join(DOMAINS) + ").",
            parameters={"type": "object", "properties": {"domain": {"type": "string", "enum": list(DOMAINS)},
                                                         "query": S}},
            handler=_devices, title="Dispositivi", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Casa", "primary": 2}),
    MCPTool(name="casa_comando", description="Comanda un dispositivo: command on|off|toggle|open|close|lock|unlock; "
            "value = luminosità % per le luci o gradi per il clima.",
            parameters={"type": "object", "properties": {"device": DEV, "command": {"type": "string", "enum": list(
                COMMANDS)}, "value": N}, "required": ["device"]},
            handler=_command, title="Comanda", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Casa", "primary": 3}),
    MCPTool(name="casa_scena", description="Attiva una scena o un'azione di Home Assistant (per nome).",
            parameters={"type": "object", "properties": {"scene": S}, "required": ["scene"]},
            handler=lambda scene: home.scene(scene), title="Scena", method="POST", clients=["telegram", "ui"],
            telegram_group=G, telegram={"section": "Scene", "primary": 4}),
    MCPTool(name="casa_preferito", description="Salva un'azione rapida: device, label, room, command (default toggle).",
            parameters={"type": "object", "properties": {"device": DEV, "label": S, "room": S, "command": {
                "type": "string", "enum": list(COMMANDS)}}, "required": ["device"]},
            handler=lambda device, label="", room="", command="toggle": (lambda f: {
                "saved": True, **f, "undo": undo("casa_preferito_elimina", favorite=f["id"])})(
                home.add_favorite(device, label, room, command)),
            title="Azione rapida", method="POST", clients=["telegram", "ui"], telegram_group=G,
            telegram={"section": "Scene"}),
    MCPTool(name="casa_preferito_esegui", description="Esegui un'azione rapida salvata.",
            parameters={"type": "object", "properties": {"favorite": S}, "required": ["favorite"]},
            handler=lambda favorite: home.run_favorite(favorite), title="Esegui azione rapida", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scene"}),
    MCPTool(name="casa_preferito_elimina", description="Elimina un'azione rapida.",
            parameters={"type": "object", "properties": {"favorite": S}, "required": ["favorite"]},
            handler=lambda favorite: home.delete_favorite(favorite), title="Elimina azione rapida", method="POST",
            clients=["telegram", "ui"], telegram_group=G, telegram={"section": "Scene"}),
], prefix="casa_")

transfer = Transfer("lares", kit.hub, sections=[
    StoreSection("preferiti", "Azioni rapide", kit.store, ["favorite"], icon="zap",
                 title=lambda r: r["data"].get("label", "")),
])
app.include_router(transfer.router())
kit.capabilities(transfer.capabilities)
kit.on_warm(lambda: threading.Thread(target=_listen, daemon=True, name="lares-ha-ws").start())
kit.webui(icon="home", color="teal", description="La casa su Home Assistant: luci, tapparelle, clima, scene, azioni rapide.",
          pages=[page("casa", "Casa", element="lares-home", icon="home", order=100,
                      help="La casa adesso, le azioni rapide e tutti i dispositivi di Home Assistant per tipo.")],
          widgets=[widget("casa", "Casa", element="lares-widget", sizes=["s", "m", "l"], size="m", auto=True,
                          open_page="casa", icon="home")],
          quick_actions=[quick_action("azione", "Casa", "POST", f"{API}/favorites/{{id}}/run", icon="home",
                                      group="Casa", source=f"{API}/quick", order=100)])
kit.finish()

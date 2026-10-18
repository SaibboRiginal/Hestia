"""WebUI plugin of Hephaestus (core module, «Sistema» section of the sidebar).

SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3: the module ships its own "inside view" on the
client plugin contract (hestia_common.plugin_client). Bundle: Hestia-Hephaestus/ui → <dist>/webui/hephaestus.js,
built in the Docker image (Node stage) and copied to /ui/dist, outside /code (the compose dev mount of app/
would hide it).

- page *Riparazioni*: remediation tasks (runbook, consent, dry-run, outcome, rollback) — read only; approving
  or undoing a repair keeps its consent path (chat/Telegram tools hephaestus_approve / hephaestus_rollback).
- widget *Forge*: state, queue, waiting review, Claude budget window; the only button is the existing
  manual brake (POST /api/hephaestus/forge/pause), after a confirm.
The Sviluppo page (Forge task list) stays built-in in the WebUI until it is ported (SPEC §A4).
Every path is under /api/hephaestus/ (remediation and Forge share it), so no duplicate endpoint is needed.
"""
from __future__ import annotations

import os

from .shared_imports import import_shared_symbol

PluginClient = import_shared_symbol("hestia_common.plugin_client", "PluginClient")
page = import_shared_symbol("hestia_common.plugin_client", "page")
widget = import_shared_symbol("hestia_common.plugin_client", "widget")

API_PREFIX = "/api/hephaestus/"
UI_DIST = os.getenv("HEPHAESTUS_UI_DIST", "/ui/dist")   # infra: where the image put the built bundle

ui = PluginClient("hephaestus", title="Hephaestus", icon="code", color="amber", kind="core", dist=UI_DIST,
                  description="Riparazioni automatiche dei servizi e auto-sviluppo (Forge).",
                  version=os.getenv("SERVICE_VERSION", "1.0.0"))
ui.webui(
    entry="hephaestus.js", api_prefix=API_PREFIX,
    pages=[page("riparazioni", "Riparazioni", element="hephaestus-repairs", icon="settings", order=170,
                help="Le riparazioni dei servizi: quale runbook, che consenso serve, se era una prova (dry-run), "
                     "com'è andata e da dove si torna indietro. Approvare o annullare resta a te, in chat o su "
                     "Telegram.")],
    widgets=[widget("forge", "Forge", element="hephaestus-forge-widget", sizes=["s", "m", "l"], size="m",
                    auto=True, icon="code",
                    help="Stato dell'auto-sviluppo: in pausa o attivo, coda, task da rivedere e finestra Claude.")],
)

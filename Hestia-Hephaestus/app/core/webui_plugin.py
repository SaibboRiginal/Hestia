"""WebUI plugin of Hephaestus (core module, «Sistema» section of the sidebar).

SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A3: the module ships its own "inside view" on the
client plugin contract (hestia_common.plugin_client). Bundle: Hestia-Hephaestus/ui → <dist>/webui/hephaestus.js,
built in the Docker image (Node stage) and copied to /ui/dist, outside /code (the compose dev mount of app/
would hide it).

- page *Riparazioni*: remediation tasks (runbook, consent, dry-run, outcome, rollback) — read only; approving
  or undoing a repair keeps its consent path (chat/Telegram tools hephaestus_approve / hephaestus_rollback).
- widget *Forge*: state, queue, waiting review, Claude budget window; the only button is the existing
  manual brake (POST /api/hephaestus/forge/pause), after a confirm.
- page *Sviluppo* (SPEC §A4, ported from the WebUI's built-in /forge page): Forge tasks (list + filters, engine
  conversation, files/diff/dossier/tests/logs/branch, approve/reject/start with engine, pause, new task, follow-up)
  and the read-only repository browser; *Copia per AI* (§B5, GET forge/tasks/export). Badge = tasks waiting for you
  (GET forge/counts → ``review``). Deep links: ``?task=<id>`` (also a short id), ``?view=repo``.
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

ui = PluginClient("hephaestus", title="Sviluppo", icon="code", color="amber", kind="core", dist=UI_DIST,
                  description="Hestia che si sviluppa da sola, con il tuo ok, e le riparazioni automatiche dei servizi.",
                  version=os.getenv("SERVICE_VERSION", "1.0.0"))
ui.webui(
    entry="hephaestus.js", api_prefix=API_PREFIX,
    pages=[page("sviluppo", "Sviluppo", element="hephaestus-sviluppo", icon="code", order=170,
                badge={"source": f"{API_PREFIX}forge/counts", "field": "review"},
                help="Forge sviluppa Hestia su rami separati: qui vedi i task, la conversazione del motore, il diff, "
                     "il dossier e i test, e decidi tu se applicare. «Copia per AI» prepara i task scelti per "
                     "un'altra AI (consegna la correzione via MCP)."),
           page("riparazioni", "Riparazioni", element="hephaestus-repairs", icon="settings", order=171,
                help="Le riparazioni dei servizi: quale runbook, che consenso serve, se era una prova (dry-run), "
                     "com'è andata e da dove si torna indietro. Approvare o annullare resta a te, in chat o su "
                     "Telegram.")],
    widgets=[widget("forge", "Forge", element="hephaestus-forge-widget", sizes=["s", "m", "l"], size="m",
                    auto=True, icon="code", open_page="sviluppo",
                    help="Stato dell'auto-sviluppo: in pausa o attivo, coda, task da rivedere e finestra Claude.")],
)

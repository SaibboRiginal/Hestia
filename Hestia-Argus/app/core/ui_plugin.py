"""Argus WebUI plugin (core module, Sistema section) — SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2/A6.

Page *Salute* (health over time, incidents and what Argus did, log viewer, Ricontrolla), widget *Stato sistema*,
quick action *Ricontrolla <servizio>* (one chip per service that is not up). Every path is under ``/api/argus/``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from hestia_common.plugin_client import PluginClient, page, quick_action, widget
except ModuleNotFoundError:  # local run: shared package next to the module
    _shared_pkg = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.plugin_client import PluginClient, page, quick_action, widget

SERVICE_VERSION = "1.0.0"
UI_DIST = os.getenv("ARGUS_UI_DIST", "/ui/dist")   # outside /code: the compose dev mount of app/ must not hide it
API = "/api/argus"

ui = PluginClient("argus", title="Argus", icon="pulse", color="green", kind="core", dist=UI_DIST,
                  description="La salute di Hestia: servizi nel tempo, incidenti, cosa ha fatto Argus, log.",
                  version=SERVICE_VERSION)
ui.webui(
    entry="argus.js", api_prefix=f"{API}/",
    pages=[page("salute", "Salute", element="argus-health", icon="pulse", order=110,
                help="Salute di ogni servizio nel tempo, incidenti aperti e cosa ha fatto Argus, log con filtri.")],
    widgets=[widget("stato", "Stato sistema", element="argus-status-widget", sizes=["s", "m", "l"], auto=True,
                    open_page="salute", icon="pulse",
                    help="Servizi sani su totale e incidenti aperti, dall'ultimo controllo di Argus.")],
    quick_actions=[quick_action("ricontrolla", "Ricontrolla", "POST", f"{API}/recheck/{{id}}", icon="refresh",
                                group="Sistema", source=f"{API}/recheck-targets", order=110)],
)

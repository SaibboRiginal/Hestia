"""Argus WebUI plugin (core module, Sistema section) — SPEC docs/work/2026-10-18-core-modules-and-external-mcp §A2/A6.

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

ui = PluginClient("argus", title="Health", icon="pulse", color="green", kind="core", dist=UI_DIST,
                  description="How the services are doing over time, incidents, what was repaired, logs.",
                  version=SERVICE_VERSION)
ui.webui(
    entry="argus.js", api_prefix=f"{API}/",
    pages=[page("salute", "Health", element="argus-health", icon="pulse", order=110,
                help="Health of each service over time, open incidents and what Argus did, logs with filters."),
           page("prestazioni", "Performance", element="argus-performance", icon="chart", order=111,
                help="Memory, processor, response time and restarts of each module, the trip through the hub, how much databases and files weigh and how fast they grow per day. Beyond the limits a notice arrives.")],
    widgets=[widget("stato", "System status", element="argus-status-widget", sizes=["s", "m", "l"], auto=True,
                    open_page="salute", icon="pulse",
                    help="Healthy services out of total and open incidents, from Argus' latest check.")],
    quick_actions=[quick_action("ricontrolla", "Recheck", "POST", f"{API}/recheck/{{id}}", icon="refresh",
                                group="System", source=f"{API}/recheck-targets", order=110)],
)

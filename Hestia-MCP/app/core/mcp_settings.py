"""MCP gateway settings declared to Themis (central settings).

Env keeps only infrastructure (Hub URL, base URL, version). Tunables are read at use time.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:
    _shared_pkg = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared_pkg) not in sys.path:
        sys.path.insert(0, str(_shared_pkg))
    from hestia_common.settings_client import SettingsClient, setting

TOOLS_CACHE_TTL = "mcp.tools.cache_ttl"
HUB_DISCOVERY_TIMEOUT = "mcp.discovery.hub_timeout"
SERVER_TIMEOUT = "mcp.calls.timeout"

settings = SettingsClient("mcp")
settings.declare([
    setting(TOOLS_CACHE_TTL, "Durata cache degli strumenti", "int", 60, group="Strumenti", min=5, max=3600,
            unit="s", help="Per quanto tengo in memoria l'elenco degli strumenti dei moduli prima di "
                           "richiederlo di nuovo. Più basso = novità viste prima, più chiamate."),
    setting(HUB_DISCOVERY_TIMEOUT, "Attesa registro di Hub", "int", 8, group="Strumenti", min=1, max=60,
            unit="s", advanced=True,
            help="Quanto aspetto Hub quando chiedo l'elenco dei moduli e dei loro strumenti."),
    setting(SERVER_TIMEOUT, "Attesa risposta di un modulo", "int", 10, group="Strumenti", min=1, max=300,
            unit="s", advanced=True,
            help="Quanto aspetto un modulo quando elenco i suoi strumenti o ne eseguo uno."),
]).declare_log_level()

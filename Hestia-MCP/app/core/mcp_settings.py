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
EXTERNAL_RATE = "mcp.external.max_calls_per_min"
OAUTH_TOKEN_MINUTES = "mcp.oauth.access_token_minutes"

settings = SettingsClient("mcp").follow_personal()
settings.declare([
    setting(TOOLS_CACHE_TTL, "Tool cache duration", "int", 60, group="Tools", min=5, max=3600,
            unit="s", help="How long I keep the modules' tool list in memory before asking again. Lower = news seen sooner, more calls."),
    setting(HUB_DISCOVERY_TIMEOUT, "Hub registry wait", "int", 8, group="Tools", min=1, max=60,
            unit="s", advanced=True,
            help="How long I wait for Hub when I ask for the list of modules and their tools."),
    setting(SERVER_TIMEOUT, "Wait for a module answer", "int", 10, group="Tools", min=1, max=300,
            unit="s", advanced=True,
            help="How long I wait for a module when I list its tools or run one."),
    setting(EXTERNAL_RATE, "Calls per minute for an external AI", "int", 60, group="External AIs", min=1, max=1000,
            unit="/min", help="How many calls per minute I accept from each external access (Claude, ChatGPT, Cursor…). Beyond it I answer 429 and the AI retries shortly after."),
    setting(OAUTH_TOKEN_MINUTES, "Duration of an OAuth token", "int", 60, group="External AIs", min=5, max=1440,
            unit="min", advanced=True,
            help="How long the token I give claude.ai or ChatGPT after consent lasts. Then the AI renews it by itself (refresh token, changed at each use); revoking access stops everything at once."),
]).declare_log_level()

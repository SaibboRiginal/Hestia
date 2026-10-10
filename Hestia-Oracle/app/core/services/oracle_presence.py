"""Assistant presence seen from the chat (SPEC docs/work/2026-10-10-assistant-presence §4.6).

Oracle reads the state BEFORE pinging (so it knows how long the user was away) and adds a
few caveman-short lines to the client instructions: state + last interaction, "be brief" when
``chat.style = brief``, and the ``chat.notice`` of overlays (e.g. busy in Forge). The full state
is available on demand through the Chronos MCP tool ``stato``.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.presence_client import PresenceClient
except ModuleNotFoundError:  # local runs without PYTHONPATH
    _shared = Path(__file__).resolve().parents[4] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.presence_client import PresenceClient

presence = PresenceClient("oracle")


def presence_instructions(state: dict | None) -> list[str]:
    """Short prompt lines from a presence state (empty when unknown or switched off)."""
    if not state or state.get("enabled") is False or state.get("show_in_chat") is False:
        return []
    lines = [presence.context_line(state)]
    if (state.get("effects") or {}).get("chat.style") == "brief":
        lines.append("Rispondi breve.")
    return [line for line in lines if line]

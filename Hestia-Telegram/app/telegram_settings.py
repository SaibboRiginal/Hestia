"""Telegram settings declared to Themis (central settings).

Env keeps only secrets and infrastructure (bot token, allowed user id, Hub/WebUI URLs,
control port, WebUI admin secret). Every tunable below is read at use time with
``settings.get(KEY)`` (``apply="live"``).

Not to be confused with ``telegram_bot/services/personal_settings.py``: those are the user's
chat preferences owned by Oracle (``oracle.chat.*``), where Telegram writes its client layer.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:
    _root = Path(__file__).resolve().parents[1]
    # Docker: /code/hestia_common next to /code/app · local: <repo>/Hestia-Shared/hestia_common.
    for _p in (_root, _root.parent / "Hestia-Shared"):
        if _p.exists() and str(_p) not in sys.path:
            sys.path.insert(0, str(_p))
    from hestia_common.settings_client import SettingsClient, setting

FEEDBACK_PROMPT_RATE = "telegram.feedback.prompt_rate"
FEEDBACK_SNOOZE_DAYS = "telegram.feedback.snooze_days"
CHAT_CLIENT_INSTRUCTIONS = "telegram.chat.client_instructions"
ORACLE_STREAM_TIMEOUT = "telegram.oracle.stream_timeout"
MENU_LAYOUT = "telegram.menu.layout"

DEFAULT_CLIENT_INSTRUCTIONS = (
    "FORMAT (the answer is shown in Telegram). Write Telegram HTML, tags ONLY: <b> <i> <u> <s> <code> <pre> "
    "<blockquote> <a href=\"url\">text</a>. FORBIDDEN: <ul> <ol> <li> <div> <span> <h1>-<h6> <p> <br/>. "
    "NEVER Markdown (**x**, _x_, ##, [x](url), tables). Lists: one line per item starting with •. "
    "No emoji. Never a bare URL: put the link on the text that describes it. Bold only for the key information."
)

settings = SettingsClient("telegram")
settings.declare([
    setting(FEEDBACK_PROMPT_RATE, "How often I ask for a rating", "float", 0.15, group="Answer rating",
            min=0, max=1,
            help="After the first answer, how often I ask you to rate an answer (0 = never, 1 = always, 0.15 = about one in seven)."),
    setting(FEEDBACK_SNOOZE_DAYS, "Default rating pause", "int", 7, group="Answer rating",
            min=1, max=365, unit="days",
            help="For how many days I stop asking for a rating when you pause without saying how long."),
    setting(CHAT_CLIENT_INSTRUCTIONS, "Format instructions for Telegram", "text", DEFAULT_CLIENT_INSTRUCTIONS,
            group="Chat", advanced=True,
            help="Format rules sent to the assistant with every message from Telegram. Tone and your personal instructions are changed in Personal."),
    setting(ORACLE_STREAM_TIMEOUT, "Longest wait for an answer", "int", 600, group="Chat",
            min=30, max=3600, unit="s", advanced=True,
            help="If the assistant stays silent this long during an answer, I stop it."),
    setting(MENU_LAYOUT, "Menu layout", "object", {}, group="Menu",
            help="How the Telegram menus are laid out: bottom keyboard, «/» commands, areas, main actions, names and emoji. Empty = default layout. It can also be changed from Telegram: Settings › Menu. An action that does not appear here still stays in its area."),
]).declare_log_level()
settings.follow_personal()      # the owner's language (people texts of the tools, hestia_common.i18n)


# ── Themis endpoints on the control server (plain http.server, no FastAPI) ──
def effective_payload() -> dict[str, Any]:
    """``GET /api/settings/effective`` — same answer as ``SettingsClient.router()``."""
    return {"owner": settings.owner, "loaded": settings._loaded, "values": settings.values(),
            "shared": dict(settings._shared), "pending_restart": settings.pending_restart()}


def reload_payload(body: dict | None) -> dict[str, Any]:
    """``POST /api/settings/reload`` — same logic as ``SettingsClient.router()``."""
    values = (body or {}).get("values")
    if isinstance(values, dict):
        changed = settings.apply(values, initial=not settings._loaded)
        if isinstance((body or {}).get("shared"), dict):
            changed = {**changed, **settings._shared_changed(body["shared"])}
    else:
        before = settings.values()
        settings.register()
        changed = {k: v for k, v in settings.values().items() if before.get(k) != v}
    return {"owner": settings.owner, "applied": sorted(changed), "pending_restart": settings.pending_restart()}

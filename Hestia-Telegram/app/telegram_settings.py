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
CHAT_LOCALE = "telegram.chat.locale"
CHAT_CLIENT_INSTRUCTIONS = "telegram.chat.client_instructions"
ORACLE_STREAM_TIMEOUT = "telegram.oracle.stream_timeout"
MENU_LAYOUT = "telegram.menu.layout"

DEFAULT_CLIENT_INSTRUCTIONS = (
    "FORMATO TELEGRAM. Scrivi in HTML di Telegram: <b>, <i>, <a href=\"url\">testo</a>, <code>, <blockquote>. "
    "Niente Markdown, niente titoli #, niente tabelle. Elenchi: una riga per voce che inizia con •. "
    "NIENTE EMOJI. Mai URL in chiaro: link sul testo che descrive. "
    "Breve: poche righe, salvo che ti chieda un elenco o i dettagli. Grassetto solo per l'informazione chiave."
)

settings = SettingsClient("telegram")
settings.declare([
    setting(FEEDBACK_PROMPT_RATE, "Frequenza della richiesta di voto", "float", 0.15, group="Voto risposte",
            min=0, max=1,
            help="Dopo la prima risposta, in che parte delle risposte ti chiedo un voto "
                 "(0 = mai, 1 = sempre, 0.15 = circa una su sette)."),
    setting(FEEDBACK_SNOOZE_DAYS, "Pausa voto predefinita", "int", 7, group="Voto risposte",
            min=1, max=365, unit="giorni",
            help="Per quanti giorni smetto di chiederti il voto quando metti in pausa senza dire quanto."),
    setting(CHAT_LOCALE, "Lingua dei messaggi formattati", "enum", "it", group="Chat",
            options=[("it", "Italiano"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"),
                     ("es", "Español")],
            help="Lingua in cui scrivo date e numeri nei risultati."),
    setting(CHAT_CLIENT_INSTRUCTIONS, "Istruzioni di formato per Telegram", "text", DEFAULT_CLIENT_INSTRUCTIONS,
            group="Chat", advanced=True,
            help="Regole di formato mandate all'assistente con ogni messaggio da Telegram. "
                 "Il tono e le tue istruzioni personali si cambiano in Personali."),
    setting(ORACLE_STREAM_TIMEOUT, "Attesa massima di una risposta", "int", 600, group="Chat",
            min=30, max=3600, unit="s", advanced=True,
            help="Se l'assistente resta in silenzio per questo tempo durante una risposta, la interrompo."),
    setting(MENU_LAYOUT, "Disposizione dei menu", "object", {}, group="Menu",
            help="Come sono disposti i menu di Telegram: tastiera in basso, comandi «/», aree, azioni principali, "
                 "nomi ed emoji. Vuoto = disposizione predefinita. Si cambia anche da Telegram: Impostazioni › Menu. "
                 "Un'azione che qui non compare resta comunque nella sua area."),
]).declare_log_level()


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

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

ALERTS_BUFFER_WINDOW = "telegram.alerts.buffer_window"
FEEDBACK_PROMPT_RATE = "telegram.feedback.prompt_rate"
FEEDBACK_SNOOZE_DAYS = "telegram.feedback.snooze_days"
COMMANDS_HIDDEN_SERVICES = "telegram.commands.hidden_services"
COMMANDS_HIDDEN = "telegram.commands.hidden"
CHAT_LOCALE = "telegram.chat.locale"
CHAT_CLIENT_INSTRUCTIONS = "telegram.chat.client_instructions"
ORACLE_STREAM_TIMEOUT = "telegram.oracle.stream_timeout"
SIGNALS_STYLE = "telegram.signals.style"
SIGNAL_FAMILIES = ("memory", "subscription", "action", "other")
SIGNALS_STYLE_BY_FAMILY = {f: f"telegram.signals.style_{f}" for f in SIGNAL_FAMILIES}

SIGNAL_STYLES = [("minimal", "Minimo"), ("compact", "Compatto"), ("rich", "Completo")]
_FAMILY_LABELS = {"memory": "memoria", "subscription": "iscrizioni", "action": "azioni",
                  "other": "altri"}

DEFAULT_CLIENT_INSTRUCTIONS = (
    "Rispondi in modo conciso (massimo 6-8 righe), personale e caldo. "
    "Parla in prima persona femminile e usa il nome dell'utente quando naturale (se lo conosci).\n\n"
    "FORMATO RICHIESTO DAL CLIENT: Markdown. "
    "Usa **grassetto**, _corsivo_, [testo descrittivo](url) per link. "
    "Per elenchi usa • (bullet) su ogni riga. "
    "NON usare tag HTML (<b>, <i>, <a>, <code>, <pre>, <br>). "
    "NON mostrare URL in chiaro. "
    "NON usare ## headings o */- per liste."
)

settings = SettingsClient("telegram")
settings.declare([
    setting(ALERTS_BUFFER_WINDOW, "Attesa per raggruppare gli avvisi", "float", 0.8, group="Avvisi",
            min=0, max=30, unit="s", advanced=True,
            help="Avvisi che arrivano entro questo tempo l'uno dall'altro finiscono in un solo messaggio."),
    setting(FEEDBACK_PROMPT_RATE, "Frequenza della richiesta di voto", "float", 0.15, group="Voto risposte",
            min=0, max=1,
            help="Dopo la prima risposta, in che parte delle risposte ti chiedo 👍/👎 "
                 "(0 = mai, 1 = sempre, 0.15 = circa una su sette)."),
    setting(FEEDBACK_SNOOZE_DAYS, "Pausa voto predefinita", "int", 7, group="Voto risposte",
            min=1, max=365, unit="giorni",
            help="Per quanti giorni smetto di chiederti il voto quando metti in pausa senza dire quanto."),
    setting(COMMANDS_HIDDEN_SERVICES, "Moduli con comandi nascosti", "list", [], group="Comandi",
            help="I comandi di questi moduli (es. scout) non compaiono nel menu di Telegram."),
    setting(COMMANDS_HIDDEN, "Comandi nascosti", "list",
            ["notifica_attiva", "notifica_disattiva", "notifiche_attive"], group="Comandi",
            help="Comandi che non compaiono nel menu di Telegram."),
    setting(CHAT_LOCALE, "Lingua dei messaggi formattati", "enum", "it", group="Chat",
            options=[("it", "Italiano"), ("en", "English"), ("de", "Deutsch"), ("fr", "Français"),
                     ("es", "Español")],
            help="Lingua in cui l'assistente scrive i risultati dei comandi."),
    setting(CHAT_CLIENT_INSTRUCTIONS, "Istruzioni di formato per Telegram", "text", DEFAULT_CLIENT_INSTRUCTIONS,
            group="Chat", advanced=True,
            help="Regole di stile e formato mandate all'assistente con ogni messaggio da Telegram. "
                 "Il tono e le tue istruzioni personali si cambiano in Personali."),
    setting(ORACLE_STREAM_TIMEOUT, "Attesa massima di una risposta", "int", 600, group="Chat",
            min=30, max=3600, unit="s", advanced=True,
            help="Se l'assistente resta in silenzio per questo tempo durante una risposta, la interrompo."),
    setting(SIGNALS_STYLE, "Stile delle notifiche brevi", "enum", "minimal", group="Notifiche brevi",
            options=SIGNAL_STYLES,
            help="Come mostro le note brevi sotto le risposte (memoria salvata, azione fatta…)."),
    # action = compact keeps what the global compose ran with before P6
    *[setting(key, f"Stile per {_FAMILY_LABELS[family]}", "enum", "compact" if family == "action" else "",
              group="Notifiche brevi",
              options=[("", "Come lo stile generale")] + SIGNAL_STYLES, advanced=True,
              help=f"Stile solo per le note di tipo {_FAMILY_LABELS[family]}.")
      for family, key in SIGNALS_STYLE_BY_FAMILY.items()],
]).declare_log_level()


def as_set(key: str) -> set[str]:
    """A list setting as a lowercase set (comma string accepted)."""
    raw = settings.get(key) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return {str(item).strip().lower() for item in raw if str(item).strip()}


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

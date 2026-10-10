"""Chronos settings declared to Themis (central settings) — assistant presence.

SPEC docs/work/2026-10-10-assistant-presence §4.7. Every knob of the presence engine is a live
setting (no env var). The hours of the night window are NOT a setting: they are the agenda window
``assistant.sleep`` the user moves/skips in Hestia's calendar.

State definitions are data too (``chronos.presence.states``, an object keyed by state): the built-in
set below is its default, so Themis gives history/undo and Oracle/Athena proposals for free.
Thresholds referenced by the definitions as ``$name`` resolve to ``chronos.presence.<name>``.
"""
from __future__ import annotations

from .shared import import_shared

_sc = import_shared("hestia_common.settings_client")
SettingsClient, setting = _sc.SettingsClient, _sc.setting

ENABLED = "chronos.presence.enabled"
IDLE_AFTER = "chronos.presence.idle_after"
NAP_AFTER = "chronos.presence.nap_after"
SLEEP_AFTER = "chronos.presence.sleep_after"
USE_SLEEP_WINDOW = "chronos.presence.use_sleep_window"
DND_DEFAULT = "chronos.presence.dnd_default_duration"
TIRED_QUOTA = "chronos.presence.tired_quota"
TIRED_DEGRADED = "chronos.presence.tired_degraded"
COUNT_UI = "chronos.presence.count_ui_actions"
ORACLE_LINE = "chronos.presence.oracle_context_line"
STATES = "chronos.presence.states"

SLEEP_WINDOW = "assistant.sleep"

# Effects every consumer may ask for (presence_client.effect). Ranked effects combine
# "most restrictive wins"; any other effect a state declares is overridden by priority.
EFFECT_ORDER: dict[str, list[str]] = {
    "work.light": ["allow", "local", "defer"],
    "work.heavy": ["allow", "local", "defer"],
    "llm.claude": ["allow", "save", "deny"],
    "notify.level": ["all", "important", "urgent"],
    "chat.style": ["normal", "brief"],
}
DEFAULT_EFFECTS: dict[str, str] = {
    "work.light": "allow", "work.heavy": "allow", "llm.claude": "allow",
    "notify.level": "all", "chat.style": "normal",
}


def _c(signal: str, op: str, value=None) -> dict:
    return {"signal": signal, "op": op, "value": value} if value is not None else {"signal": signal, "op": op}


# when = list of groups (OR); each group = list of clauses (AND). Empty → never matches.
BUILTIN_STATES: dict[str, dict] = {
    "awake": {
        "kind": "base", "core": True, "priority": 90, "label": "Sveglio", "emoji": "🟢",
        "help": "Stai interagendo: i lavori in background aspettano, Claude è per le tue chat.",
        "when": [[_c("user.idle_minutes", "<", "$idle_after")]],
        "effects": {"work.light": "defer", "work.heavy": "defer", "llm.claude": "save",
                    "notify.level": "all", "chat.style": "normal"},
    },
    "idle": {
        "kind": "base", "core": True, "priority": 10, "label": "In attesa", "emoji": "🟡",
        "help": "Nessuna interazione da qualche minuto: partono i lavori leggeri (Athena pensa).",
        "when": [[_c("user.idle_minutes", ">=", "$idle_after")]],
        "effects": {"work.light": "allow", "work.heavy": "defer", "llm.claude": "save",
                    "notify.level": "all"},
    },
    "dnd": {
        "kind": "base", "core": True, "priority": 100, "label": "Non disturbare", "emoji": "🔕",
        "help": "Attivato da te: passano solo le notifiche urgenti.",
        "when": [[_c("manual.dnd", "true")]],
        "effects": {"work.light": "allow", "work.heavy": "local", "llm.claude": "save",
                    "notify.level": "urgent"},
    },
    "nap": {
        "kind": "base", "priority": 60, "label": "Pisolino", "emoji": "😴",
        "help": "Assente da un po' di giorno: anche lavori pesanti locali, Claude no.",
        "when": [[_c("user.idle_minutes", ">=", "$nap_after"), _c(f"agenda.window.{SLEEP_WINDOW}", "false")]],
        "effects": {"work.light": "allow", "work.heavy": "local", "llm.claude": "save",
                    "notify.level": "important"},
    },
    "deep_sleep": {
        "kind": "base", "priority": 70, "label": "Sonno profondo", "emoji": "🌙",
        "help": "Notte o assenza lunga: tutto permesso, anche Forge con Claude; solo notifiche urgenti, "
                "le altre in un riepilogo al risveglio.",
        "when": [[_c(f"agenda.window.{SLEEP_WINDOW}", "true"), _c("setting.use_sleep_window", "true")],
                 [_c("setting.sleep_after", ">", 0), _c("user.idle_minutes", ">=", "$sleep_after")]],
        "effects": {"work.light": "allow", "work.heavy": "allow", "llm.claude": "allow",
                    "notify.level": "urgent"},
    },
    "busy": {
        "kind": "overlay", "priority": 50, "label": "Occupato: {activities}", "emoji": "🔨",
        "help": "C'è un lavoro pesante in corso: ne parte uno alla volta.",
        "when": [[_c("activity.heavy_count", ">", 0)]],
        "effects": {"work.heavy": "defer"},
        "notice": "sto lavorando ({activities}), rispondo un po' più lento",
    },
    "eating": {
        "kind": "overlay", "priority": 55, "label": "Sto mangiando", "emoji": "🍝",
        "help": "Manutenzione: deploy, riavvii, modello in caricamento.",
        "when": [[_c("activity.maintenance_count", ">", 0)]],
        "effects": {"work.heavy": "defer"},
        "notice": "mi sto aggiornando, la risposta può tardare",
    },
    "tired": {
        "kind": "overlay", "priority": 40, "label": "Stanco", "emoji": "🥱",
        "help": "Quota Claude bassa o moduli in errore: risparmia Claude, risposte più brevi.",
        "when": [[_c("resource.claude_quota_left", "<", "$tired_quota")],
                 [_c("health.degraded_services", ">=", "$tired_degraded")]],
        "effects": {"llm.claude": "save", "chat.style": "brief"},
    },
}
CORE_STATES = tuple(k for k, v in BUILTIN_STATES.items() if v.get("core"))

_G = "Presenza"
settings = SettingsClient("chronos")
settings.declare([
    setting(ENABLED, "Stato di attività dell'assistente", "bool", True, group=_G, oracle="read", order=1,
            help="Se spento resta sempre «Sveglio» senza effetti: i moduli usano solo le loro finestre."),
    setting(IDLE_AFTER, "In attesa dopo", "int", 5, group=_G, min=1, max=240, unit="min", order=10,
            help="Minuti senza interazioni prima di passare da «Sveglio» a «In attesa»."),
    setting(NAP_AFTER, "Pisolino dopo", "int", 45, group=_G, min=1, max=1440, unit="min", order=11,
            help="Minuti senza interazioni (fuori dalla notte) prima del «Pisolino»."),
    setting(SLEEP_AFTER, "Sonno profondo dopo", "int", 180, group=_G, min=0, max=2880, unit="min", order=12,
            help="Minuti senza interazioni prima del «Sonno profondo» a qualsiasi ora; 0 = solo di notte."),
    setting(USE_SLEEP_WINDOW, "Usa la finestra notte", "bool", True, group=_G, order=13,
            help="Di notte (finestra «assistant.sleep» dell'agenda, 01–07) va in sonno profondo. "
                 "Gli orari si cambiano dal calendario."),
    setting(DND_DEFAULT, "Durata di «Non disturbare»", "int", 120, group=_G, min=5, max=1440, unit="min",
            order=14, help="Quanto dura «Non disturbare» se non dici fino a quando."),
    setting(TIRED_QUOTA, "Stanco sotto la quota Claude", "int", 25, group=_G, min=0, max=100, unit="%",
            order=20, help="Sotto questa quota Claude rimasta prima del reset è «Stanco» e risparmia Claude."),
    setting(TIRED_DEGRADED, "Stanco con moduli in errore", "int", 2, group=_G, min=1, max=20, order=21,
            help="Con almeno tanti moduli in errore (Argus) è «Stanco»."),
    setting(COUNT_UI, "Contano le azioni nella WebUI", "bool", True, group=_G, order=30,
            help="Inviare, cliccare un comando, salvare nella WebUI conta come interazione "
                 "(le semplici visite alle pagine no)."),
    setting(ORACLE_LINE, "L'assistente vede il suo stato", "bool", True, group=_G, order=31,
            help="Una riga nel contesto della chat: stato e ultima interazione (es. per dire «bentornato»)."),
    setting(STATES, "Definizioni degli stati", "object", BUILTIN_STATES, group=_G, advanced=True, order=90,
            help="Stati come dati: kind base/overlay, priority, label, when (gruppi di condizioni sui segnali), "
                 "effects. «Sveglio», «In attesa» e «Non disturbare» sono stati chiave: si modificano ma "
                 "non si cancellano. Ripristina per tornare agli stati predefiniti."),
])
settings.declare_log_level()


def threshold(name: str):
    """``$name`` in a condition → value of ``chronos.presence.<name>``."""
    return settings.get(f"chronos.presence.{name}")

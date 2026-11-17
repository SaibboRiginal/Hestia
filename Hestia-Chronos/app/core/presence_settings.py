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
    "chat.reply": ["live", "queued"],
}
DEFAULT_EFFECTS: dict[str, str] = {
    "work.light": "allow", "work.heavy": "allow", "llm.claude": "allow",
    "notify.level": "all", "chat.style": "normal", "chat.reply": "live",
}


def _c(signal: str, op: str, value=None) -> dict:
    return {"signal": signal, "op": op, "value": value} if value is not None else {"signal": signal, "op": op}


# when = list of groups (OR); each group = list of clauses (AND). Empty → never matches.
BUILTIN_STATES: dict[str, dict] = {
    "awake": {
        "kind": "base", "core": True, "priority": 90, "label": "Awake", "emoji": "🟢", "icon": "sun", "tone": "success",
        "help": "You are using me: Forge and heavy jobs wait for you to leave, so I stay fast and Claude is not used up automatically.",
        "when": [[_c("user.idle_minutes", "<", "$idle_after")]],
        "effects": {"work.light": "defer", "work.heavy": "defer", "llm.claude": "save",
                    "notify.level": "all", "chat.style": "normal"},
    },
    "idle": {
        "kind": "base", "core": True, "priority": 10, "label": "Waiting", "emoji": "🟡", "icon": "clock", "tone": "warning",
        "help": "No interaction for a few minutes: light jobs start (Athena reflects), heavy ones still wait.",
        "when": [[_c("user.idle_minutes", ">=", "$idle_after")]],
        "effects": {"work.light": "allow", "work.heavy": "defer", "llm.claude": "save",
                    "notify.level": "all"},
    },
    "dnd": {
        "kind": "base", "core": True, "priority": 100, "label": "Do not disturb", "emoji": "🔕", "icon": "bell-off", "tone": "danger",
        "help": "You turned it on: you get only urgent notifications, the others in a summary when you turn it off or it ends.",
        "when": [[_c("manual.dnd", "true")]],
        "effects": {"work.light": "allow", "work.heavy": "local", "llm.claude": "save",
                    "notify.level": "urgent"},
    },
    "nap": {
        "kind": "base", "priority": 60, "label": "Nap", "emoji": "😴", "icon": "moon", "tone": "muted",
        "help": "Away for a while during the day: local heavy jobs too, Claude not.",
        "when": [[_c("user.idle_minutes", ">=", "$nap_after"), _c(f"agenda.window.{SLEEP_WINDOW}", "false")]],
        "effects": {"work.light": "allow", "work.heavy": "local", "llm.claude": "save",
                    "notify.level": "important"},
    },
    "deep_sleep": {
        "kind": "base", "priority": 70, "label": "Deep sleep", "emoji": "🌙", "icon": "moon", "tone": "accent",
        "help": "Night or long absence: everything allowed, Forge with Claude too; only urgent notifications, the others in a summary when you wake up.",
        "when": [[_c(f"agenda.window.{SLEEP_WINDOW}", "true"), _c("setting.use_sleep_window", "true")],
                 [_c("setting.sleep_after", ">", 0), _c("user.idle_minutes", ">=", "$sleep_after")]],
        "effects": {"work.light": "allow", "work.heavy": "allow", "llm.claude": "allow",
                    "notify.level": "urgent"},
    },
    "busy": {
        "kind": "overlay", "priority": 50, "label": "Busy: {activities}", "emoji": "🔨", "icon": "wrench", "tone": "accent",
        "help": "A heavy job is running: one starts at a time.",
        "when": [[_c("activity.heavy_count", ">", 0)]],
        "effects": {"work.heavy": "defer"},
        "notice": "I'm working ({activities}), I answer a bit more slowly",
    },
    "eating": {
        "kind": "overlay", "priority": 55, "label": "Eating", "emoji": "🍝", "icon": "refresh", "tone": "info",
        "help": "Maintenance: deploys, restarts, model loading.",
        "when": [[_c("activity.maintenance_count", ">", 0)]],
        "effects": {"work.heavy": "defer"},
        "notice": "I'm updating, the answer may take a while",
    },
    "tired": {
        "kind": "overlay", "priority": 40, "label": "Tired", "emoji": "🥱", "icon": "battery-low", "tone": "warning",
        "help": "Claude quota low or modules with errors: save Claude, shorter answers.",
        "when": [[_c("resource.claude_quota_left", "<", "$tired_quota")],
                 [_c("health.degraded_services", ">=", "$tired_degraded")]],
        "effects": {"llm.claude": "save", "chat.style": "brief"},
    },
    # Oracle down longer than argus.oracle.grace (signal from Argus, SPEC docs/work/2026-10-19-oracle-offline).
    # Back to chat.reply=live → Chronos asks the chat clients to answer their queues.
    "oracle_offline": {
        "kind": "overlay", "priority": 95, "label": "Unavailable", "emoji": "⏳", "icon": "hourglass", "tone": "warning",
        "help": "I can't answer right now: commands, notifications and agenda work; chat messages stay queued and will be answered as soon as possible. Proactive jobs wait.",
        "when": [[_c("oracle.offline", "true")]],
        "effects": {"work.light": "defer", "work.heavy": "defer", "chat.reply": "queued"},
        "notice": "I can't answer right now, I'll answer as soon as possible",
    },
    # Only fallback models answer for longer than argus.oracle.grace (signal from Argus, oracle-offline v3 E).
    "oracle_limited": {
        "kind": "overlay", "priority": 90, "label": "Limited", "emoji": "🔋", "icon": "battery-low", "tone": "warning",
        "help": "I answer, but in a reduced way: the main models are not available. Heavy jobs wait.",
        "when": [[_c("oracle.limited", "true")]],
        "effects": {"work.heavy": "defer", "chat.style": "brief"},
        "notice": "I answer in a reduced way until the main models come back",
    },
}
CORE_STATES = tuple(k for k, v in BUILTIN_STATES.items() if v.get("core"))

_G = "Presence"
settings = SettingsClient("chronos").follow_personal()      # owner language for fixed texts (i18n)
settings.declare([
    setting(ENABLED, "Assistant activity state", "bool", True, group=_G, oracle="read", order=1,
            help="If off it always stays «Awake» with no effects: modules use only their own windows."),
    setting(IDLE_AFTER, "Waiting after", "int", 5, group=_G, min=1, max=240, unit="min", order=10,
            help="Minutes without interaction before moving from «Awake» to «Waiting»."),
    setting(NAP_AFTER, "Nap after", "int", 45, group=_G, min=1, max=1440, unit="min", order=11,
            help="Minutes without interaction (outside the night) before the «Nap»."),
    setting(SLEEP_AFTER, "Deep sleep after", "int", 180, group=_G, min=0, max=2880, unit="min", order=12,
            help="Minutes without interaction before «Deep sleep» at any hour; 0 = only at night."),
    setting(USE_SLEEP_WINDOW, "Use the night window", "bool", True, group=_G, order=13,
            help="At night (agenda window «assistant.sleep», 01–07) it goes into deep sleep. The hours are changed from the calendar."),
    setting(DND_DEFAULT, "Duration of «Do not disturb»", "int", 120, group=_G, min=5, max=1440, unit="min",
            order=14, help="How long «Do not disturb» lasts if you don't say until when."),
    setting(TIRED_QUOTA, "Tired below the Claude quota", "int", 25, group=_G, min=0, max=100, unit="%",
            order=20, help="Below this Claude quota left before the reset it is «Tired» and spares Claude."),
    setting(TIRED_DEGRADED, "Tired with failing modules", "int", 2, group=_G, min=1, max=20, order=21,
            help="With at least this many modules failing (Argus) it is «Tired»."),
    setting(COUNT_UI, "WebUI actions count", "bool", True, group=_G, order=30,
            help="Sending, clicking a command, saving in the WebUI counts as interaction (simple page visits don't)."),
    setting(ORACLE_LINE, "The assistant sees its own state", "bool", True, group=_G, order=31,
            help="One line in the chat context: state and last interaction (e.g. to say «welcome back»)."),
    setting(STATES, "State definitions", "object", BUILTIN_STATES, group=_G, advanced=True, order=90,
            help="States as data: kind base/overlay, priority, label, when (groups of conditions on the signals), effects. «Awake», «Waiting» and «Do not disturb» are key states: they can be changed but not deleted. Restore to go back to the default states."),
])
settings.declare_log_level()


def threshold(name: str):
    """``$name`` in a condition → value of ``chronos.presence.<name>``."""
    return settings.get(f"chronos.presence.{name}")

"""Hermes settings declared to Themis (central settings).

Env keeps only infrastructure (Hub/Archive URLs, base URL, version, Hub registration
plumbing, startup wait). Every tunable below is read at use time (``apply="live"``).
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

DELIVERY_MAX_ATTEMPTS = "hermes.delivery.max_attempts"
DELIVERY_RETRY_INTERVAL = "hermes.delivery.retry_interval"
DEDUPE_RECURRING_MAX_AGE = "hermes.dedupe.recurring_max_age"
DEDUPE_RECURRING_TYPES = "hermes.dedupe.recurring_types"
BATCH_WINDOW = "hermes.batch.window"
BATCH_MAX_ATTEMPTS = "hermes.batch.max_attempts"
RETRACT_AFTER = "hermes.retract.after"
REPEAT_RESET_AFTER_DAYS = "hermes.repeat.reset_after_days"
PENDING_REMIND_HOURS = "hermes.attesa.richiamo_ore"
ACTIVE_CLIENT_MINUTES = "hermes.consegna.client_attivo_minuti"
NOTIFICATION_STYLE = "hermes.notifiche.stile"
STYLES = [("scheda", "Card"), ("frase", "{assistant}'s sentence")]

settings = SettingsClient("hermes")
settings.declare([
    setting(DELIVERY_MAX_ATTEMPTS, "Delivery attempts per client", "int", 6, group="Delivery",
            min=1, max=50,
            help="How many times I try to deliver a notification to a client (Telegram, WebUI) before giving up for that client."),
    setting(DELIVERY_RETRY_INTERVAL, "Interval between attempts", "int", 120, group="Delivery",
            min=15, max=3600, unit="s", advanced=True,
            help="How often I retry failed deliveries."),
    setting(DEDUPE_RECURRING_MAX_AGE, "Repeat recurring notices after", "int", 3600, group="Anti-duplicati",
            min=60, max=86400, unit="s",
            help="A recurring notice (e.g. module in error) already sent is not repeated before this time; after it, if the problem persists, I notify you again."),
    setting(DEDUPE_RECURRING_TYPES, "Recurring notice types", "list",
            ["service.action_required", "service.health"], group="Anti-duplicati", advanced=True,
            help="Event types the timed repetition applies to; the others are never repeated."),
    setting(BATCH_WINDOW, "Wait to group listings", "int", 30, group="Raggruppamento",
            min=5, max=1800, unit="s",
            help="After a new listing I wait this long with nothing new and then send you a single message with all those arrived."),
    setting(BATCH_MAX_ATTEMPTS, "Attempts for a group of listings", "int", 6, group="Raggruppamento",
            min=1, max=20, advanced=True,
            help="How many times I retry sending a group of listings (with growing waits) before giving up."),
    setting(RETRACT_AFTER, "Remove handled notifications from the chat after", "int", 6, group="Cleanup",
            min=1, max=46, unit="h",
            help="Notifications already seen or handled disappear from the Telegram chat after this time (they stay in the WebUI list). Telegram allows deleting them only within 48 h."),
    setting(REPEAT_RESET_AFTER_DAYS, "Reset the reminder counter after", "int", 30, group="Reminders",
            min=1, max=365, unit="days",
            help="A repeated reminder (e.g. a routine) counts how many times you skipped it. If it does not come for this long, the count starts again from zero."),
    setting(PENDING_REMIND_HOURS, "Remind me of things to decide after", "int", 4, group="To decide",
            min=1, max=72, unit="h",
            help="If a notification waiting for your answer stays there for this long, I send you a single reminder with all those waiting (once for each)."),
    setting(ACTIVE_CLIENT_MINUTES, "Ring only where you are using me, for", "int", 10, group="Delivery",
            min=0, max=240, unit="min",
            help="If you used me from an app (Telegram, WebUI) in these minutes, the notification rings only there; in the others it arrives silently. 0 = rings everywhere."),
    setting(NOTIFICATION_STYLE, "Notification style", "enum", "scheda", group="Delivery", options=STYLES,
            help="Card: as always. {assistant}'s sentence: informative notifications arrive as a short sentence of hers, as in chat; warnings, errors and those with buttons or questions stay cards."),
]).declare_log_level().follow_personal()   # assistant name, she/he, owner: the «frase» style speaks as her


def notification_style() -> str:
    value = str(settings.get(NOTIFICATION_STYLE) or "scheda")
    return value if value in {k for k, _ in STYLES} else "scheda"


def recurring_event_types() -> frozenset[str]:
    raw = settings.get(DEDUPE_RECURRING_TYPES) or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return frozenset(str(e).strip() for e in raw if str(e).strip())

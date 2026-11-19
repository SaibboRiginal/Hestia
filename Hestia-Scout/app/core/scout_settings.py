"""Scout settings declared to Themis (central settings).

Replace the old tunable env vars (SCOUT_POLL_INTERVAL_SECONDS — gone with the mail poll, Scout now gets
its mails by push from Iris — SCOUT_EMAIL_SENDERS,
SCOUT_FILTER_QUERIES, SCOUT_*_BATCH_*, SCOUT_LLM_TIMEOUT_SECONDS, SCOUT_RECONCILE_EVERY_CYCLES,
SCOUT_ENABLE_LISTING_ENRICHMENT, LOG_LEVEL). All live: read at the point of use.
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

MAIL_SENDERS = "scout.mail.senders"
MAIL_FILTER_QUERIES = "scout.mail.filter_queries"
BATCH_MIN_SIZE = "scout.batch.min_size"
BATCH_MAX_SIZE = "scout.batch.max_size"
BATCH_DEBOUNCE = "scout.batch.debounce"
BATCH_COOLDOWN = "scout.batch.cooldown"
LLM_TIMEOUT = "scout.llm.timeout"
RECONCILE_EVERY_CYCLES = "scout.reconcile.every_cycles"
ENRICHMENT_ENABLED = "scout.enrichment.enabled"
NOTIFY_VOICE = "scout.notifications.voice"

DEFAULT_SENDERS = ["nonrispondere@idealista.it", "noreply@notifiche.immobiliare.it"]  # external-name: the site's own address

settings = SettingsClient("scout").follow_personal()      # owner language for fixed texts (i18n)
settings.declare([
    setting(MAIL_SENDERS, "Listing senders", "list", list(DEFAULT_SENDERS), group="Email check",
            order=1,
            help="Addresses (or domains) of the real estate portals: Iris passes their emails to Scout as soon as they arrive. Ignored if you set custom email searches."),
    setting(MAIL_FILTER_QUERIES, "Custom email searches", "list", [], group="Email check",
            order=2, advanced=True,
            help="Explicit email searches (one per line, e.g. FROM \"address\"). If empty the senders are used."),
    setting(BATCH_MIN_SIZE, "Fewest emails to start", "int", 1, group="Listing extraction", min=1, max=50,
            order=10, advanced=True,
            help="Scout waits to have at least this many new emails before extracting the listings."),
    setting(BATCH_MAX_SIZE, "Emails per model call", "int", 5, group="Listing extraction", min=1, max=50,
            order=11, advanced=True,
            help="How many emails it sends together to the model. Higher = fewer but longer calls."),
    setting(BATCH_DEBOUNCE, "Wait to collect emails", "int", 45, group="Listing extraction", min=0, max=600,
            unit="s", order=12, advanced=True,
            help="Before extracting it waits a moment to collect emails that arrived almost together (0 = at once)."),
    setting(BATCH_COOLDOWN, "Pause between one group and the next", "int", 15, group="Listing extraction", min=0,
            max=600, unit="s", order=13, advanced=True,
            help="Pause between two model calls, so as not to exceed quota limits."),
    setting(LLM_TIMEOUT, "Longest extraction time", "int", 120, group="Listing extraction", min=10, max=900,
            unit="s", order=14, advanced=True,
            help="How long to wait for the model's answer for a group of emails before trying the next."),
    setting(RECONCILE_EVERY_CYCLES, "Reconciliation every N cycles", "int", 1, group="Data maintenance",
            min=0, max=100, order=20, advanced=True,
            help="Every how many cycles Scout checks the saved properties again (position, dates, link). 0 = never."),
    setting(ENRICHMENT_ENABLED, "Enrich from the listing page", "bool", True, group="Data maintenance",
            order=21,
            help="Opens the listing page to complete description and address and retries the ones left half done."),
    # Same key as hestia_common.reminders.voice_setting: off, a list of houses reads badly aloud.
    setting(NOTIFY_VOICE, "Notifications by voice too", "bool", False, group="Notifications", order=30,
            help="Besides the text you get a voice message (Telegram) or a play button (site) for new houses."),
]).declare_log_level()


def _as_list(value, sep: str) -> list[str]:
    items = value.split(sep) if isinstance(value, str) else (value or [])
    return [str(i).strip() for i in items if str(i).strip()]


def mail_rule_parts() -> tuple[list[str], list[str]]:
    """``(senders, queries)`` of Scout's Iris subscription: explicit searches win over the sender list."""
    explicit = _as_list(settings.get(MAIL_FILTER_QUERIES), "||")
    if explicit:
        return [], explicit
    return _as_list(settings.get(MAIL_SENDERS), ","), []


def get_int(key: str, floor: int | None = None) -> int:
    """Integer setting, clamped to ``floor``; bad value → declared default."""
    try:
        value = int(settings.get(key))
    except (TypeError, ValueError):
        value = int(settings._defs[key]["default"])
    return max(floor, value) if floor is not None else value

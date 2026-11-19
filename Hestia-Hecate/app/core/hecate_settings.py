"""Hecate settings declared to Themis (central settings).

Env keeps only secrets (OAuth client ids/secrets/tokens), infrastructure (URLs, token/tunnel files)
and credential-bound deployment choices (provider enable flags, OAuth flow mode/scopes).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from hestia_common.settings_client import SettingsClient, setting
except ModuleNotFoundError:  # local run outside the container: use the workspace copy
    _shared = Path(__file__).resolve().parents[3] / "Hestia-Shared"
    if str(_shared) not in sys.path:
        sys.path.insert(0, str(_shared))
    from hestia_common.settings_client import SettingsClient, setting

CALENDAR_BACKFILL_DAYS = "hecate.calendar.backfill_days"
ARCHIVE_ROUTE_TIMEOUT = "hecate.archive.route_timeout"
CALENDAR_WRITE_TIMEOUT = "hecate.archive.calendar_write_timeout"
AUTH_RECHECK_INTERVAL = "hecate.auth.recheck_interval"
ACTION_NOTIFY_COOLDOWN = "hecate.auth.notify_cooldown"
MAIL_WATCH_INTERVAL = "hecate.mail.watch_interval"
MAIL_SAFETY_INTERVAL = "hecate.mail.safety_interval"
WEATHER_CACHE_MINUTES = "hecate.weather.cache_minutes"
PERSONAL_PLACES = "themis.personal.places"
PHONE_HOME_WIFI = "hecate.phone.home_wifi"
PHONE_APPS = "hecate.phone.app"
GMAIL_PUSH_TOPIC = "hecate.gmail.push_topic"
GMAIL_PUSH_SUBSCRIPTION = "hecate.gmail.push_subscription"

settings = SettingsClient("hecate")
settings.declare([
    setting(CALENDAR_BACKFILL_DAYS, "Past days to sync", "int", 7, group="Calendar",
            min=0, max=365, unit="days",
            help="How many days back I read from the calendars (Google/Outlook) at each sync. More days = more past events imported, slower sync."),
    setting(ARCHIVE_ROUTE_TIMEOUT, "Wait to save data", "int", 8, group="Archive",
            min=1, max=120, unit="s", advanced=True,
            help="How many seconds I wait for the Archive when I save data. If it is slow, raise it."),
    setting(CALENDAR_WRITE_TIMEOUT, "Wait to save events", "int", 10, group="Archive",
            min=1, max=120, unit="s", advanced=True,
            help="How many seconds I wait for the Archive when I save a calendar event."),
    setting(AUTH_RECHECK_INTERVAL, "Account access check", "int", 3600, group="alt::Account",
            min=0, max=86400, unit="s",
            help="Every how many seconds I check again that Google/Outlook are still linked and, if not, I tell you again. 0 = only at startup."),
    setting(ACTION_NOTIFY_COOLDOWN, "Pause between identical notices", "int", 300, group="alt::Account",
            min=0, max=86400, unit="s", advanced=True,
            help="Shortest time between two identical notices (e.g. 'link Google again'), so you don't get duplicates."),
    setting(MAIL_WATCH_INTERVAL, "New email check", "int", 900, group="Email", min=60, max=86400,
            unit="s",
            help="How often I look for new emails (one light check for all of {assistant}: then Iris passes them to the interested modules). It is the default recurrence of the agenda job."),
    setting(MAIL_SAFETY_INTERVAL, "Safety check with Gmail push", "int", 21600, group="Email",
            min=300, max=86400, unit="s", advanced=True,
            help="When Gmail push notifications (Pub/Sub) are on, the periodic check is only a safety net and moves to this interval."),
    setting(WEATHER_CACHE_MINUTES, "Weather forecast validity", "int", 30, group="Weather", min=5, max=360,
            unit="min", advanced=True,
            help="For how many minutes I reuse the forecast already downloaded for a place before asking again (the weather service updates the data about every hour)."),
    setting(PHONE_HOME_WIFI, "Home Wi-Fi", "list", [], group="Phone",
            help="Names of the home Wi-Fi networks: when the phone is connected to one of these you are «home». Empty = the phone must say it itself (home field)."),
    setting(PHONE_APPS, "Apps to listen to", "list", [], group="Phone",
            help="Notifications from these apps (e.g. the bank, Satispay) go to the modules that use them, like expenses. Empty = all the phone sends."),
    # Set from the «Gmail instant notices» card (Connections): Settings shows a link to it.
    setting(GMAIL_PUSH_TOPIC, "Gmail instant notices: topic", "string", "", group="Email", editor="connection:hecate.gmail_push",
            advanced=True, help="The Google Cloud Pub/Sub topic Gmail writes to (projects/<project>/topics/<topic>)."),
    setting(GMAIL_PUSH_SUBSCRIPTION, "Gmail instant notices: subscription", "string", "", group="Email",
            editor="connection:hecate.gmail_push", advanced=True,
            help="The pull subscription Hestia reads (projects/<project>/subscriptions/<sub>)."),
]).declare_log_level().follow_personal()

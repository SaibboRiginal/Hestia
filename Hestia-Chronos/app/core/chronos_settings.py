"""Chronos settings declared to Themis (central settings) — agenda, calendar sync, reminders.

Same owner/client as the presence settings (``presence_settings.settings``, owner ``chronos``): one
SettingsClient per module. Every value is read at use time (``apply="live"``): loops re-read it each
iteration, so a change applies without restart. Env keeps only infrastructure (Hub URL, port, version,
startup wait, ``TZ``).

Not settings on purpose:
- how often the calendar is synced: it is the recurrence of the agenda job ``chronos.calendar_sync``
  (900 s is only its code default; the user moves/pauses it in the agenda — paused = no sync);
- the timezone: the container ``TZ`` (same as every module), no Chronos-only duplicate.
"""
from __future__ import annotations

from .presence_settings import settings
from .shared import import_shared

AGENDA_TICK = "chronos.agenda.tick_seconds"
AGENDA_MAX_ATTEMPTS = "chronos.agenda.max_attempts"
FLEX_GAP = "chronos.flex.gap_minutes"
CATCHUP_MAX_AGE = "chronos.catchup.max_age_hours"
SYNC_CALENDAR_ID = "chronos.sync.calendar_id"
SYNC_LOOK_BACK_DAYS = "chronos.sync.look_back_days"
SYNC_LOOK_AHEAD_DAYS = "chronos.sync.look_ahead_days"
SYNC_NOTIFY_NEW = "chronos.sync.notify_new"
REMINDERS_POLL = "chronos.reminders.poll_seconds"
REMINDERS_LOOK_AHEAD_HOURS = "chronos.reminders.look_ahead_hours"

_setting = import_shared("hestia_common.settings_client").setting

settings.declare([
    _setting(AGENDA_TICK, "Agenda check every", "int", 60, group="Agenda", min=15, max=600, unit="s",
             advanced=True, order=10,
             help="How often I look for a job or a task of the assistant to run."),
    _setting(AGENDA_MAX_ATTEMPTS, "Attempts for a task", "int", 5, group="Agenda", min=1, max=50,
             advanced=True, order=11,
             help="A one-off task that fails is retried up to this many times, then it is «failed»."),
    _setting(FLEX_GAP, "Margin from your commitments", "int", 15, group="Agenda", min=0, max=120, unit="min", order=12,
             help="Tasks with a flexible time (e.g. the evening recap) start at least this far from the start or end of one of your commitments."),
    _setting(CATCHUP_MAX_AGE, "Recover skipped tasks up to", "int", 6, group="Agenda", min=0, max=48,
             unit="hours", order=13,
             help="When I'm available again I redo the tasks that failed while I was away, if they are more recent than this; older ones I only list in the «While I was away» message."),
    _setting(SYNC_NOTIFY_NEW, "Tell me about new events", "bool", True, group="Calendar", order=20,
             help="When a new future event appears in Google/Outlook I send you a notice."),
    _setting(SYNC_LOOK_AHEAD_DAYS, "Import events up to", "int", 30, group="Calendar", min=1, max=365,
             unit="days", order=21,
             help="How many days ahead I import from external calendars."),
    _setting(SYNC_LOOK_BACK_DAYS, "Import past events from", "int", 1, group="Calendar", min=0, max=90,
             unit="days", advanced=True, order=22,
             help="How many days back I reread, to catch changes to events just past."),
    _setting(SYNC_CALENDAR_ID, "Calendar to import", "string", "primary", group="Calendar",
             advanced=True, order=23,
             help="ID of the Google/Outlook calendar read; «primary» = the main one."),
    _setting(REMINDERS_LOOK_AHEAD_HOURS, "First reminder", "int", 26, group="Reminders", min=3, max=168,
             unit="h", order=30,
             help="How many hours before an event the first reminder arrives (then 2 hours and 30 minutes before)."),
    _setting(REMINDERS_POLL, "Reminder check every", "int", 300, group="Reminders", min=30,
             max=3600, unit="s", advanced=True, order=31,
             help="How often I check whether there is a reminder to send."),
])

# Weekly coach plan (SPEC docs/work/2026-10-20-coach-of-every-kind §10). When the plan is built is the agenda job
# ``chronos.coach_week`` (move or pause it in the agenda), not a setting.
COACH_DAY_START = "chronos.coach.day_start"
COACH_DAY_END = "chronos.coach.day_end"
COACH_BUFFER = "chronos.coach.buffer_minutes"
COACH_MAX_BLOCKS = "chronos.coach.max_blocks_per_day"
COACH_MAX_MINUTES = "chronos.coach.max_minutes_per_day"

settings.follow_personal()      # themis.personal.week_start: the plan's week
settings.declare([
    _setting(COACH_DAY_START, "The plan starts at", "time", "07:00", group="Weekly plan", order=40,
             help="Before this hour I put nothing in the plan."),
    _setting(COACH_DAY_END, "The plan ends at", "time", "22:00", group="Weekly plan", order=41,
             help="After this hour I put nothing in the plan."),
    _setting(COACH_BUFFER, "Margin around commitments", "int", 15, group="Weekly plan", min=0, max=120,
             unit="min", order=42, help="Free time I leave before and after each event in your calendar."),
    _setting(COACH_MAX_BLOCKS, "Most blocks per day", "int", 2, group="Weekly plan", min=1, max=6,
             order=43, help="How many timed tasks (e.g. a workout) I put in a day at most."),
    _setting(COACH_MAX_MINUTES, "Most minutes per day", "int", 120, group="Weekly plan", min=15,
             max=600, unit="min", order=44, help="How much plan time at most in a single day."),
])

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
SYNC_CALENDAR_ID = "chronos.sync.calendar_id"
SYNC_LOOK_BACK_DAYS = "chronos.sync.look_back_days"
SYNC_LOOK_AHEAD_DAYS = "chronos.sync.look_ahead_days"
SYNC_NOTIFY_NEW = "chronos.sync.notify_new"
REMINDERS_POLL = "chronos.reminders.poll_seconds"
REMINDERS_LOOK_AHEAD_HOURS = "chronos.reminders.look_ahead_hours"

_setting = import_shared("hestia_common.settings_client").setting

settings.declare([
    _setting(AGENDA_TICK, "Controllo dell'agenda ogni", "int", 60, group="Agenda", min=15, max=600, unit="s",
             advanced=True, order=10,
             help="Ogni quanto guardo se c'è un lavoro o un'attività dell'assistente da eseguire."),
    _setting(AGENDA_MAX_ATTEMPTS, "Tentativi per un'attività", "int", 5, group="Agenda", min=1, max=50,
             advanced=True, order=11,
             help="Un'attività una tantum che fallisce viene riprovata fino a tante volte, poi è «fallita»."),
    _setting(FLEX_GAP, "Margine dai tuoi impegni", "int", 15, group="Agenda", min=0, max=120, unit="min", order=12,
             help="Le attività con orario flessibile (es. il recap della sera) partono almeno così lontano "
                  "dall'inizio o dalla fine di un tuo impegno."),
    _setting(SYNC_NOTIFY_NEW, "Avvisami dei nuovi eventi", "bool", True, group="Calendario", order=20,
             help="Quando un nuovo evento futuro compare in Google/Outlook ti mando un avviso."),
    _setting(SYNC_LOOK_AHEAD_DAYS, "Importa eventi fino a", "int", 30, group="Calendario", min=1, max=365,
             unit="giorni", order=21,
             help="Quanti giorni avanti importo dai calendari esterni."),
    _setting(SYNC_LOOK_BACK_DAYS, "Importa eventi passati da", "int", 1, group="Calendario", min=0, max=90,
             unit="giorni", advanced=True, order=22,
             help="Quanti giorni indietro rileggo, per prendere modifiche a eventi appena passati."),
    _setting(SYNC_CALENDAR_ID, "Calendario da importare", "string", "primary", group="Calendario",
             advanced=True, order=23,
             help="ID del calendario Google/Outlook letto; «primary» = quello principale."),
    _setting(REMINDERS_LOOK_AHEAD_HOURS, "Primo promemoria", "int", 26, group="Promemoria", min=3, max=168,
             unit="h", order=30,
             help="Quante ore prima di un evento arriva il primo promemoria (poi 2 ore e 30 minuti prima)."),
    _setting(REMINDERS_POLL, "Controllo dei promemoria ogni", "int", 300, group="Promemoria", min=30,
             max=3600, unit="s", advanced=True, order=31,
             help="Ogni quanto controllo se c'è un promemoria da mandare."),
])

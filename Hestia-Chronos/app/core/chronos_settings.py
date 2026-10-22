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
    _setting(AGENDA_TICK, "Controllo dell'agenda ogni", "int", 60, group="Agenda", min=15, max=600, unit="s",
             advanced=True, order=10,
             help="Ogni quanto guardo se c'è un lavoro o un'attività dell'assistente da eseguire."),
    _setting(AGENDA_MAX_ATTEMPTS, "Tentativi per un'attività", "int", 5, group="Agenda", min=1, max=50,
             advanced=True, order=11,
             help="Un'attività una tantum che fallisce viene riprovata fino a tante volte, poi è «fallita»."),
    _setting(FLEX_GAP, "Margine dai tuoi impegni", "int", 15, group="Agenda", min=0, max=120, unit="min", order=12,
             help="Le attività con orario flessibile (es. il recap della sera) partono almeno così lontano "
                  "dall'inizio o dalla fine di un tuo impegno."),
    _setting(CATCHUP_MAX_AGE, "Recupera le attività saltate fino a", "int", 6, group="Agenda", min=0, max=48,
             unit="ore", order=13,
             help="Quando torno disponibile rifaccio le attività che non sono riuscite mentre non c'ero, se sono "
                  "più recenti di così; le più vecchie le elenco soltanto nel messaggio «Mentre non c'ero»."),
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

# Weekly coach plan (SPEC docs/work/2026-10-20-coach-di-ogni-tipo §10). When the plan is built is the agenda job
# ``chronos.coach_week`` (move or pause it in the agenda), not a setting.
COACH_DAY_START = "chronos.coach.day_start"
COACH_DAY_END = "chronos.coach.day_end"
COACH_BUFFER = "chronos.coach.buffer_minutes"
COACH_MAX_BLOCKS = "chronos.coach.max_blocks_per_day"
COACH_MAX_MINUTES = "chronos.coach.max_minutes_per_day"

settings.follow_personal()      # themis.personal.week_start: the plan's week
settings.declare([
    _setting(COACH_DAY_START, "Il piano inizia alle", "time", "07:00", group="Piano della settimana", order=40,
             help="Prima di quest'ora non metto niente nel piano."),
    _setting(COACH_DAY_END, "Il piano finisce alle", "time", "22:00", group="Piano della settimana", order=41,
             help="Dopo quest'ora non metto niente nel piano."),
    _setting(COACH_BUFFER, "Margine attorno agli impegni", "int", 15, group="Piano della settimana", min=0, max=120,
             unit="min", order=42, help="Tempo libero che lascio prima e dopo ogni evento del tuo calendario."),
    _setting(COACH_MAX_BLOCKS, "Blocchi al giorno al massimo", "int", 2, group="Piano della settimana", min=1, max=6,
             order=43, help="Quante attività con un orario (es. allenamento) metto al massimo in un giorno."),
    _setting(COACH_MAX_MINUTES, "Minuti al giorno al massimo", "int", 120, group="Piano della settimana", min=15,
             max=600, unit="min", order=44, help="Quanto tempo del piano al massimo in un solo giorno."),
])

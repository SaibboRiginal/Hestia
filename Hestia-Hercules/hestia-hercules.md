# Hestia-Hercules 🏋️

**Role:** Gym coach — exercises, workout templates, live sessions (offline), records, progress, goals, adaptation;
light outdoor activities (run, bike, walk) planned with the weather
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · WebUI plugin bundle (Lit, `ui/`)
**Port:** 19019 · Dossier: `docs/work/2026-10-17-coach-module/`

---

## Responsibility

- Gym / weights; outdoor activities only as light intentions and a done/not-done log (no GPS, pace or heart
  rate: Garmin stays the tracker). See «Outdoor activities» below.
- Owns the training logic: catalog (115 seeded exercises, Italian names, muscles, joints, equipment, pattern),
  templates (workout types) with progression rules, programs (weekly or rotation), live sessions, sets,
  measurements, goals, check-ins, feedback, adaptations, day plans (skip / move).
- Computes everything derived: e1RM (Epley/Brzycki), PRs, volume per muscle/group, progression suggestions
  (double, linear, rpe), stalls and deload hint, goal progress and streak, warm-ups, plate maths.
  Bodyweight exercises plan what you type (extra load, assistance), never the bodyweight-based load the records use:
  `bodyweight_reps` and `assisted_bodyweight` progress by reps only, `weighted_bodyweight` adds kilos to the ballast.
- **Adaptation is a conversation**: the assistant calls `fitness_adapt_today` with what Marko says (pain,
  energy, time, missing equipment, intent); Hercules applies its rules and returns the plan + trace; nothing is
  applied until `fitness_apply_adaptation`; `fitness_restore_today` goes back. No Hermes proposal cards.
- Does not call models (Oracle is the brain) and has no database (Archive `hercules-store`).

## Storage and offline sync

- Archive `/api/hercules-store/records`: one table `hercules_records (kind, id)` with `data` JSONB,
  `parent_id`, `ref_id`, `at`, `updated_at`, `deleted` tombstone, `seq` (global sequence = sync cursor).
  Writes are last-write-wins by `updated_at`; older writes come back in `stale`.
- Hercules keeps an in-memory mirror pulled by cursor. Archive away → reads keep working on the mirror
  (`[🔄] event=hercules_mirror_refresh_failed`), writes answer 503.
- Archive data epoch: store answers carry `epoch`; when it changes (a backup rollback swapped the database) the mirror is dropped and reloaded from zero (`[🔄] event=hercules_mirror_reset reason=data_epoch`), so no stale row is written back.
- Clients: `GET /api/hercules/bootstrap` once, then the outbox goes to `POST /api/hercules/sync`
  `{device_id, cursor, ops:[{op_id, kind, id, action: upsert|delete, fields, updated_at}]}` →
  `{applied, rejected, stale, changes, cursor, suggestions}`. Ops are idempotent (replay safe); ids are client UUIDs.

## Assistant

- Tools (`fitness` domain via `module_tool_domains`, REST path `/api/hercules/tools/<name>`): `fitness_summary`,
  `next_workout`, `history`, `exercise_stats`, `search_exercises`, `templates`, `start_session`, `log_sets`
  (natural text: "panca 80x8, 80x8; trazioni 8, 7"), `finish_session`, `checkin`, `adapt_today`,
  `apply_adaptation`, `restore_today`, `skip_day`, `postpone`, `feedback`, `edit_template`, `undo_template`,
  `log_measurement`, `set_goal`, `plan_activity`, `confirm_activity`, `log_activity`, `activities`,
  `activity_outcome`, `cancel_activity` (all prefixed `fitness_`).
- `GET /api/module/context?budget=&topic=`: short lines (next workout, week vs goal, recent PRs, stalls, feedback to
  discuss). With `topic=<signal key>` the text explains that signal (`stall:<exercise>` → last 4 exposures,
  `pr:<exercise>` → records of the last 14 days, `missed_streak` → which days, `deload` → the low check-ins,
  `week_goal` → goal hint and days left); an unknown topic answers the normal line. Same shape `{module, domain,
  updated_at, text}`, cut to `budget`.
- `GET /api/module/recap?day=&next=`: piece «Allenamento» of the daily recap (sessions with sets/minutes, records, a
  planned day skipped or missed, next workout, goal note) plus outdoor lines: activities done, slots not done or
  still to mark, slots planned tomorrow (`Activities.recap`). Plain facts, capability `recap_endpoint`.
- Template edits by the assistant keep the previous revision (`POST /templates/{id}/undo`).

## Reflection signals (`app/core/signals.py`, docs/work/2026-10-20-riflessione-a-livelli)

Deterministic facts published to Archive `signals-store` through `hestia_common.signals_client` (module `hercules`,
domain `fitness`); texts say «Allenamento» things, never the module name. No LLM, no new judging logic.

| Key | Kind · severity | When | Page |
|---|---|---|---|
| `stall:<exercise_id>` | trend · attenzione | `progression.stall` (setting `hercules.stall.exposures`), exercise trained in the last 30 days | `esercizi/<id>` |
| `deload` | trend · attenzione | ≥ 3 check-ins with energy ≤ 2 in 7 days | `allenamento` |
| `missed_streak` | streak · attenzione (alta ≥ 4) | ≥ 2 planned days of the weekly program missed in a row (skipped/moved days neither count nor break) | `allenamento` |
| `pr:<exercise_id>` | milestone · info, ttl 3 days | `records.recent_prs` of the last 3 days | `esercizi/<id>` |
| `week_goal` | goal · attenzione | a weekly goal `behind` with ≤ 2 days left | `progressi` |

Weekly metrics (last 12 ISO weeks, current included; weeks before the first workout left out): `fitness.sessions`
«Allenamenti», `fitness.volume` «Volume (kg)», `fitness.energy` «Energia media» (only weeks with check-ins).

When: `signals.changed()` (debounced re-evaluation) after sync with ops, session finish/delete, set delete, check-in,
quick done/undo, import, the MCP finish/check-in tools and once after warm-up; agenda job `hercules.signals` (daily
17:30, editable in the agenda) → `POST /api/hercules/signals/run` → `{written, retracted, signals, metrics}`.

## Reminders (off by default)

Agenda job `hercules.reminder` (daily 18:30, editable in the agenda) → `POST /api/hercules/reminder/check`.
Sends only when enabled, a goal is behind, nothing done or skipped today, no live session, and under
`hercules.reminder.max_per_week`. Hermes `service.action_required` with `replaces: hercules.reminder`
(one live reminder) and actions **Segna fatto** (`resolves: true`) / **Salta oggi**; target `owner`;
`_link` opens the plugin page `allenamento`.

## Client UI (plugin contract)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Favourites star (warning), streaks flame, records trophy, rest timer; energy 1–5 as numbers (1 with battery-low).

Bundle `ui/src/index.ts` → `/ui/webui/hercules.js` (built in the Dockerfile). Pages: allenamento (today / live),
schede, schede/:id, esercizi, esercizi/:id, storico, storico/:id, progressi, corpo. Widgets: prossimo (name always visible; exercise list only in size l), settimana,
fatto, record, esercizio, muscoli, peso, live (settimana also shows «Corsa 1/2» per open intention). Quick actions:
fatto (one tap per template, undo), inizia, peso, corsa («Ho corso», km optional, undo), salta.
A UI change needs `up-all.bat --build hercules`.

## Settings (Themis, `hercules.*`)

units, rest.default_seconds, bar_weight, plates, warmup.scheme, increment.{barbell,dumbbell,machine,cable},
e1rm_formula, stall.exposures, adapt.low_energy, adapt.weight_cut_pct, skip_mode, reminder.enabled (false),
reminder.max_per_week (2) and notifiche.voce (true: the reminder also arrives as a voice message / «Ascolta») from
`hestia_common.reminders`. Week start is the personal setting
`themis.personal.week_start` (shared by every module).

## API (via Hub `/route/hercules/...`)

See `Hestia-Swagger/swagger.yml` tag *Hercules*. Main groups: bootstrap/sync, exercises, templates (+undo),
programs, next, sessions (start, start-next, log-text, sets, finish, discard), plans/days (skip, postpone),
checkin, feedback, adapt (+apply, restore), measurements, stats, records, goals, summary, quick (Home chips),
import (Strong/Hevy CSV preview + commit, idempotent), export (csv/json), reminder/check, activities (week,
propose, `{plan}/confirm`, `{plan}/slots` (+`/{slot}/done|missed|moved|ask`), `{plan}/keep`, `DELETE {plan}`, log,
`DELETE log/{id}`, quick-run, morning, sync-calendar), signals/run.

## Export and import (`/api/transfer/*`, dossier `docs/work/2026-10-20-import-export`)

Sections (hestia_common.transfer over `hercules-store`): `esercizi` (exercise) · `schede` (template, program) ·
`sessioni` (session + its sets) · `misure` (measurement) · `obiettivi` (goal, plan) · `feedback` (checkin, feedback).
Choosing a session pulls its template and exercises. Reminder and adaptation rows are runtime state: never exported.
Settings travel through Themis.

## Configuration (infrastructure only)

`SERVICE_NAME`, `SERVICE_BASE_URL`, `HUB_API_URL`, `TZ` (local day for goals/streaks), `HERCULES_UI_DIST`.

## Tests

`python -m pytest -q -m "unit or api" Hestia-Hercules/tests` (fake Archive in memory, no network; `test_signals.py`
mocks the signals transport).


## Coach of the weekly plan (dossier `docs/work/2026-10-20-coach-di-ogni-tipo` §7.1)

Hub tag `coach`; `app/core/coach.py` mounted with `hestia_common.coach.CoachRouter`.
- **Needs**: a weekly program → one `workout.<weekday>` block per program day still to do this week; otherwise an
  "N a settimana" goal → one `workout` block with `count` = what is left. Tags `workout`, `effort:N`, muscle groups;
  deload suggested → lower effort and a note. No goal and no weekly program → no need.
- **Fit**: the adaptation engine's time-limit rule (short version of the day's workout).
- **Placed**: kept in memory; the summary says «Nel piano: giovedì 18:30» and the reminder gives the time.
- **Reports** (`CoachClient`, background): done on finish/quick done/sync, skipped on skip day, changed on postpone
  and on goal/program save. **Review**: sessions done vs the weekly goal, deload/stall flags.
- Settings: `hercules.coach.time_of_day` (evening), `hercules.coach.min_minutes` (30), group «Piano della settimana».


## Outdoor activities (dossier `docs/work/2026-10-20-meteo-hecate` §3.8)

`app/core/activities.py`. «Ho voglia di correre 2 volte questa settimana» → `fitness_plan_activity` picks the best
slots of the week (pure `score_hour`/`best_of_day`/`pick_slots`): dry, daylight, comfortable temperature, little wind,
free in Marko's calendars (Hecate events) and not on top of another planned slot; back-to-back days avoided when
there is a choice. Weather = Hecate forecast at the place (saved place name, city, or Casa). Nothing reaches the
calendar before `fitness_confirm_activity` (all slots, some by number, or times Marko chose).
- **Calendar «Allenamenti»** (Google, ensured through Hecate `calendars`): one event per confirmed slot (30' reminder),
  each finished gym session and each logged activity → training history. Marko's other events are never touched.
  Done/missed shows as ✓/✗ in the Google title (Google has no icons). Links in store kind `calendar_link`.
- **«L'hai fatto?»**: agenda task `hercules.activity.<slot>` 30' after the slot → Hermes (key = the task key)
  with Fatto / Non fatto / Spostato (moved = the best slot left this week or the given time). Answering in chat or
  the plugin closes the live question (Hermes `closes`).
- **Morning coach** agenda job `hercules.activity_morning` (daily 07:30, editable): only with an open intention
  still behind; rain on today's slot → «Pioggia alle 19:00 per la corsa: meglio alle 11:00?» (Sposta / Tengo);
  otherwise a good window today → «Ottimo giorno per la corsa: 18:00–18:45, 16°, Sereno · Corsa 0/2» (Pianifica /
  Non oggi). At most one message a day (`activity_nudge`).
- **Weekly plan**: open intentions with times neither done nor planned are coach needs `activity.<plan>` (block,
  tag `outdoor`, priority `could`); the planner keeps them out of rainy/dark hours. A log reports `done`.
- Store kinds `activity_plan`, `activity` (written by the server only; refused from the offline sync),
  `calendar_link`, `activity_nudge`.

## From the watch (feed `wearable.daily`, dossier `docs/work/2026-10-24-tutto-brainstorm-cindy` W4 B10)

Hecate pushes each day read from Garmin to `POST /api/hercules/wearable` (`hestia_common.feeds`, declared as
`capabilities.feeds`). Outdoor activities (corsa, bici, camminata, nuoto) become done activities like «Ho corso»
(`activities.log(..., ext="garmin:<id>")`: a planned slot that day is closed); each device activity is logged once,
and one the owner deleted never comes back. Strength workouts stay with the gym sessions. Today's sleep score and
morning body battery (or training readiness), 0–100 → 1–5, become the day's check-in (`source: device`) only when
there is no check-in made by hand; the adaptation of today's workout reads it like any check-in.

## Telegram card (`display`)
`GET /api/hercules/summary` and `GET /api/hercules/next` (tools `fitness_summary`, `fitness_next_workout`) return a `display` card: the week lines with Inizia / Come mi sento (or Registra serie / Concludi during a session); the next workout with exercises, sets and suggested weight, buttons Inizia (preset template) / Adatta a come sto / Sposta / Salta oggi. Built with `hestia_common.display`; Hestia-MCP keeps it only for Telegram (docs/work/2026-10-23-telegram-da-zero §6).

## Module guide for the assistant (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, Cindy 30)
The Hub registration declares `capabilities.when_to_use` (one line in the assistant's «MODULI» index) and
`capabilities.manual` (short manual the assistant loads with `module_manual` only when it needs it).

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: Counts through the SDK `plural()` («1 esercizio», «1 allenamento»); templates offline text «Apri Allenamento…».

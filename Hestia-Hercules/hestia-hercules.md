# Hestia-Hercules 🏋️

**Role:** Gym coach — exercises, workout templates, live sessions (offline), records, progress, goals, adaptation
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · WebUI plugin bundle (Lit, `ui/`)
**Port:** 19019 · Dossier: `docs/work/2026-10-17-coach-module/`

---

## Responsibility

- Gym / weights only (cardio and sports stay on Garmin).
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
- Clients: `GET /api/hercules/bootstrap` once, then the outbox goes to `POST /api/hercules/sync`
  `{device_id, cursor, ops:[{op_id, kind, id, action: upsert|delete, fields, updated_at}]}` →
  `{applied, rejected, stale, changes, cursor, suggestions}`. Ops are idempotent (replay safe); ids are client UUIDs.

## Assistant

- Tools (`fitness` domain via `module_tool_domains`, REST path `/api/hercules/tools/<name>`): `fitness_summary`,
  `next_workout`, `history`, `exercise_stats`, `search_exercises`, `templates`, `start_session`, `log_sets`
  (natural text: "panca 80x8, 80x8; trazioni 8, 7"), `finish_session`, `checkin`, `adapt_today`,
  `apply_adaptation`, `restore_today`, `skip_day`, `postpone`, `feedback`, `edit_template`, `undo_template`,
  `log_measurement`, `set_goal` (all prefixed `hercules_`).
- `GET /api/module/context`: short lines (next workout, week vs goal, recent PRs, stalls, feedback to discuss).
- Template edits by the assistant keep the previous revision (`POST /templates/{id}/undo`).

## Reminders (off by default)

Agenda job `hercules.reminder` (daily 18:30, editable in the agenda) → `POST /api/hercules/reminder/check`.
Sends only when enabled, a goal is behind, nothing done or skipped today, no live session, and under
`hercules.reminder.max_per_week`. Hermes `service.action_required` with `replaces: hercules.reminder`
(one live reminder) and actions **Segna fatto** (`resolves: true`) / **Salta oggi**; target `owner`;
`_link` opens the plugin page `allenamento`.

## Client UI (plugin contract)

Icons, never emoji (DESIGN-SYSTEM rule, `docs/work/2026-10-20-icone-nei-client`): `<hxk-icon name tone>`. Favourites star (warning), streaks flame, records trophy, rest timer; energy 1–5 as numbers (1 with battery-low).

Bundle `ui/src/index.ts` → `/ui/webui/hercules.js` (built in the Dockerfile). Pages: allenamento (today / live),
schede, schede/:id, esercizi, esercizi/:id, storico, storico/:id, progressi, corpo. Widgets: prossimo, settimana,
fatto, record, esercizio, muscoli, peso, live. Quick actions: fatto (one tap per template, undo), inizia, peso, salta.
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
import (Strong/Hevy CSV preview + commit, idempotent), export (csv/json), reminder/check.

## Configuration (infrastructure only)

`SERVICE_NAME`, `SERVICE_BASE_URL`, `HUB_API_URL`, `TZ` (local day for goals/streaks), `HERCULES_UI_DIST`.

## Tests

`python -m pytest -q -m unit Hestia-Hercules/tests` (fake Archive in memory, no network).

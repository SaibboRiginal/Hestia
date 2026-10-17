# SPEC — Coach: workout tracking & adaptive training module

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User via external chat (Claude Code cloud project, thread "Modulo Coach allenamenti") · 2026-10-17 |
| **Status** | Draft — waiting for Marko's confirmation (no code yet) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the project chat 2026-10-17): new modules that enrich what the
assistant knows about me, built **complete like serious standalone apps**. The coach: like any progress
tracking app — progress, statistics, exercises, weights / sets / reps per exercise, history, workout types
that group exercises — plus talking with the AI to adjust them depending on how I'm doing ("I can't make it",
"bad day", …). Must be functional, easy to use (good UX/UI), and usable by the AI through MCP like every module.
UI lives in clients through the **module plugin contract** (sibling thread "Plugin dei moduli nei client"):
pages always visible, widgets for dashboards (Oracle may build dashboards), per-client show/hide.

Sibling modules designed in parallel: Guardaroba (wardrobe), Self care. §9 lists what the three share.

---

## 1. Goal

A new **domain module `Hestia-Coach`** (domain `fitness`, like Scout owns `real_estate`) that is a complete
strength-training tracker (reference apps: Strong, Hevy, JEFIT) with Hestia's extra: the assistant knows my
training and can **adapt today's workout** to how I feel, using rules that live in Coach, not in Oracle.

## 2. Scope

### In (v1)
- Exercise catalog: seeded library (~120 common exercises, Italian names + English aliases) + my custom ones.
- Workout templates ("schede") grouping exercises with targets; folders; optional weekly **program**.
- Live workout logging (sets, weight, reps, RPE/RIR, set types, rest timer, supersets, notes).
- History, personal records, statistics, progress charts, body measurements.
- Progression engine (what to lift next time) and deload/stall detection — deterministic, in Coach.
- Readiness check-in + **adaptation engine** (bad day, little time, pain, no equipment, skipped day).
- MCP tools for the assistant; a short on-demand context summary.
- Agenda integration (planned days, reminders via Chronos → Hermes); settings in Themis.
- WebUI pages + widgets through the plugin contract; Telegram quick logging via chat/commands.
- Import (Strong / Hevy CSV) and export (CSV / JSON).

### Out (v1, kept for later — see §10)
Cardio GPS tracking, wearables / Health Connect sync, progress photos, exercise demo videos, nutrition,
social features, a mobile-native app.

## 3. Data model (stored in Archive, owned by Coach)

Archive gets a pure-storage area `/api/coach-store/*` (same pattern as settings-store / presence-store:
typed tables, CRUD + range queries, no business rules). All ids UUID, all rows `created_at/updated_at`,
soft delete (`archived`) so history never loses an exercise.

| Table | Key fields |
|---|---|
| `coach_exercises` | name, aliases[], kind (`weight_reps` · `bodyweight_reps` · `weighted_bodyweight` · `assisted_bodyweight` · `reps_only` · `duration` · `distance_duration`), primary_muscles[], secondary_muscles[], stress_joints[] (for the pain rule), movement_pattern (squat · hinge · push_h · push_v · pull_h · pull_v · lunge · carry · core · isolation), equipment (`barbell` · `dumbbell` · `machine` · `cable` · `kettlebell` · `band` · `bodyweight` · `other`), unilateral, increment_kg (null = setting by equipment), notes, instructions, media_url, is_custom, archived |
| `coach_templates` | name, folder, notes, color, estimated_minutes, position, archived |
| `coach_template_items` | template_id, exercise_id, position, superset_group, rest_seconds, notes, **targets**: list of planned sets `{type, reps_min, reps_max, weight_kg?, rpe?, duration_s?, distance_m?}`, progression rule (`double` · `linear` · `rpe` · `none`) |
| `coach_programs` | name, active, start_date, weeks (null = repeating), schedule `[{weekday or day_index, template_id}]`, deload_every_weeks? |
| `coach_sessions` | started_at, ended_at, template_id?, program_id?, name, status (`active` · `done` · `discarded`), notes, readiness `{energy, sleep, soreness, stress, pain_areas[], free_text}`, adaptation_id?, bodyweight_kg?, perceived_effort (1–10) |
| `coach_session_exercises` | session_id, exercise_id, position, superset_group, notes, replaced_from_exercise_id? |
| `coach_sets` | session_exercise_id, position, type (`warmup` · `normal` · `drop` · `failure`), weight_kg, reps, rpe?, rir?, duration_s?, distance_m?, completed, completed_at |
| `coach_measurements` | taken_at, kind (`bodyweight` · `body_fat` · `waist` · `chest` · `arm` · `thigh` · … custom), value, unit |
| `coach_adaptations` | created_at, session_id?, input (readiness + request), output (modified plan), rule_trace[], accepted |

Derived data (PRs, e1RM, volumes) is **computed by Coach**, not stored as truth; Coach may keep a cache
table `coach_records` (exercise_id, record kind, value, set_id, achieved_at) rebuilt from sets on any edit.
Weights are stored in kg; display unit is a setting (kg/lb).

## 4. Features (what makes it a "serious app")

### 4.1 Exercises
Search by name/alias, filter by muscle and equipment; detail page with my history of that exercise,
PR list, e1RM chart, last 5 sessions, notes. Create/edit custom, merge duplicates, archive.

### 4.2 Templates and programs
Build a scheda: add exercises, planned sets (with rep ranges, target RPE, set types), rest per exercise,
supersets (drag to group), reorder by drag. Duplicate, folders. A program maps weekdays (or day 1..N
rotation) to templates; "next workout" is computed from the program and what I actually did.

### 4.3 Live workout (the core screen, mobile first)
- Start from template, from "next in program", or empty.
- Each exercise shows **"last time"** values next to every set and the **progression suggestion** pre-filled.
- Tap ✓ to complete a set → rest timer starts (per-exercise rest, ±15 s, skip); browser notification +
  vibration on end. Timer survives page reload (derived from `completed_at`).
- Edit weight/reps inline with large steppers; RPE picker; set type by long-press/menu; add/remove set,
  add exercise, swap exercise (suggests same-muscle alternatives), reorder.
- Plate calculator (bar weight + available plates from settings) and warm-up generator (e.g. 40/60/80 %).
- Duration counter, total volume live, finish → summary (duration, volume, sets, new PRs 🎉), notes,
  perceived effort, "update template with today's values?".
- One active session at a time; discard asks confirmation. State saved on every change (no lost workouts).

### 4.4 History
Calendar/heatmap and list of sessions; session detail with edit after the fact; filter by template/exercise.

### 4.5 Records and statistics
- PR kinds per exercise: heaviest weight, best e1RM (Epley default, Brzycki selectable), most reps at a
  weight, best set volume, best session volume; rep-range PRs (1, 3, 5, 8, 10, 12 RM).
- Charts: e1RM / top set per exercise over time, weekly volume (tonnage and **hard sets per muscle group**),
  frequency per muscle, workouts per week, duration, streak (weeks hitting the weekly target), adherence to
  program, bodyweight and measurements trends.
- Period selector (4 w / 3 m / 1 y / all); comparisons "this month vs last".

### 4.6 Body
Log bodyweight and circumferences, charts, optional link of bodyweight to sessions (for bodyweight
exercises volume).

### 4.7 Import / export
Import Strong and Hevy CSV exports (exercise names mapped to the catalog, unknowns become custom after a
review step). Export everything as CSV (one row per set) and JSON.

## 5. Coach engines (deterministic, in Coach — Oracle only calls them)

### 5.1 Progression (next-time suggestion)
- `double` (default for hypertrophy ranges): all sets at the top of the rep range at target RPE → +increment;
  else same weight, aim for +1 rep.
- `linear`: success → +increment each session; 2 consecutive misses → −10 % reset.
- `rpe`: next weight from last top set's e1RM and the target reps × RPE table.
- Increment from exercise, else setting by equipment (barbell 2.5, dumbbell 2, machine 5, cable 2.5).
- **Stall detection**: no e1RM gain in N exposures (setting, default 3) → suggestion "deload or change
  variation"; optional scheduled deload weeks in the program (−40 % sets, same weight or −10 %).

### 5.2 Adaptation ("bad day", "no time", "pain", "skip")
Input (structured; Oracle fills it from my words): `energy 1–5`, `time_minutes?`, `pain_areas[]`,
`soreness[]`, `equipment_missing[]`, `mood/free_text`, `intent` (`lighter` · `shorter` · `swap` · `skip` ·
`postpone` · `harder`). Output: a modified copy of today's plan + a human-readable trace of the rules applied.

Rules (each a small, testable function, thresholds as settings):
| Situation | Rule |
|---|---|
| energy 1–2 | keep compounds, drop accessories after the first 2 exercises, sets −1/−2, target RPE −1/−2, weight −10 % |
| energy 4–5 + readiness good | allow top-set attempt (+1 set or +increment) on the main lift |
| time limit | estimate minutes (sets × (work + rest)); drop lowest-priority items first, then supersets accessories, then cut sets |
| pain in area X | remove/replace exercises loading X (muscle + joint map in the catalog: `stress_joints[]`), never "push through"; message suggests a professional if pain repeats |
| soreness in muscle | lower volume for that muscle, swap to a less fatiguing variant |
| equipment missing | swap to same pattern/muscle with available equipment |
| skip | mark planned day skipped; program shifts (rotation) or keeps calendar (weekly) per setting; reminder moved via agenda |
| postpone | agenda item moved to the chosen day/time |
| repeated low energy (≥3 check-ins in 7 days) | propose a deload week (proposal, see 5.3) |

Today's adaptation applies **directly** to today's session when I ask (it's my request, reversible: "ripristina
scheda originale"). It never changes the template.

### 5.3 Permanent changes
Changes to templates/programs suggested by the assistant or by the engines (deload week, swap an exercise
for good, raise a rep range) are **proposals**: Coach stores them and sends them to me through **Hermes**
(message + Accept/Reject buttons, `service.action_required`, like Themis proposals). When I ask a change
myself in chat ("togli lo squat dalla scheda A"), the assistant calls the edit tool directly — I asked it.

## 6. Assistant integration

### 6.1 MCP tools (`hestia_common.mcp_helpers.MCPTool`, domain `fitness`)
Read: `coach_summary` (week at a glance, next workout, recent PRs, stalls, readiness trend — caveman text),
`coach_next_workout`, `coach_history` (range/exercise filter), `coach_exercise_stats` (e1RM trend, PRs),
`coach_search_exercises`, `coach_templates`, `coach_records`.
Write: `coach_start_session`, `coach_log_sets` (natural logging: "panca 80x8, 80x8, 77.5x7"), `coach_finish_session`,
`coach_checkin` (readiness), `coach_adapt_today`, `coach_restore_today`, `coach_skip_day`, `coach_postpone`,
`coach_edit_template` (only on my explicit request), `coach_propose_change` (→ Hermes), `coach_log_measurement`.
Telegram-visible commands (group "Allenamento"): oggi, inizia, log, fine, check-in, salta, statistiche.

### 6.2 Context for the assistant
On demand, consistent with Themis ("Oracle knows itself on demand"): Oracle's classifier gets a `fitness`
domain (`preference_domains.py`) so these tools load only when relevant; `coach_summary` is the compact
context. Optional cross-module line (shared contract, §9): a ≤1-line summary ("Allenamento: Push A oggi ·
3/4 sett. · PR panca 85 kg") a module may expose for the assistant's daily context.
Memory facts stay in Oracle/Archive memory; Coach data stays in Coach (no duplication into memory).

### 6.3 Proactivity (all via agenda, no timers)
Registered with `agenda_client` (keys `coach.*`, I can edit/pause them like any agenda rule):
`coach.reminder` (planned days, at the setting time → Hermes "Oggi: Push A · 55 min"), `coach.missed`
(evening check: planned but not done → Hermes asks "saltato o spostiamo?" with buttons Skip / Tomorrow /
Ignore), `coach.weekly_review` (Sunday: week summary, PRs, stalls). Presence: reminders respect
`notify.level` through Hermes (no logic in Coach).

## 7. Settings (Themis, `settings_client.setting(...)`, no env)
`coach.units` (kg/lb) · `coach.rest.default_seconds` (90) · `coach.increment.<equipment>` · `coach.bar_weight`
(20) · `coach.plates` (list) · `coach.e1rm_formula` (epley/brzycki) · `coach.week_start` (monday) ·
`coach.weekly_target` (sessions, 3) · `coach.stall.exposures` (3) · `coach.adapt.*` thresholds ·
`coach.reminder.time` · `coach.missed.enabled` · `coach.skip_mode` (shift/keep) · `coach.warmup.scheme`.
Env: only `COACH_PORT` / Hub URL (infrastructure).

## 8. Clients (UI through the plugin contract — implemented after that contract is on main)

### 8.1 WebUI pages (always visible, per-client show/hide from the contract)
"Allenamento" with sub-pages: **Oggi** (next workout card, check-in, start; becomes the live workout),
**Schede** (templates + program editor), **Esercizi** (catalog + exercise detail), **Storico**,
**Progressi** (stats/charts), **Corpo**. Follows `DESIGN-SYSTEM.md`; side panels resizable with `<hx-resize>`;
mobile-first live workout (bottom-anchored controls, big tap targets, works one-handed, dark-friendly).

### 8.2 Widgets (for dashboards, also composable by Oracle)
Next workout · This week (sessions/target, streak, volume) · Recent PRs · Exercise progress chart
(param: exercise) · Muscle volume map (param: period) · Bodyweight trend · Active workout (timer + current set).

### 8.3 Telegram
Commands from Hub discovery (6.1), natural-language logging through Oracle, Hermes reminders with buttons.
No rest timer on Telegram (WebUI only).

## 9. Shared with Guardaroba and Self care (to align, not to duplicate)
- Storage pattern: Archive `/api/<module>-store/*` typed tables, pure storage; the module owns logic.
- Plugin contract for pages/widgets (sibling thread owns it).
- Optional assistant context line + on-demand `<module>_summary` tool (same naming).
- Proposals for permanent changes → Hermes, same `service.action_required` shape as Themis.
- Health/safety tone: Coach never pushes through pain, no medical advice.

## 10. Later (not v1)
Progress photos (Archive file store) · exercise images/video · cardio sessions with GPS/heart rate ·
Health Connect / Garmin / Apple Health import · AI-generated programs from goals (Coach rules + Oracle
wording) · nutrition link · 3D/heat muscle map.

## 11. Phases (each shippable alone)
| Phase | Content |
|---|---|
| **P1** | `Hestia-Coach` service (FastAPI, Dockerfile, compose global, Hub registration, port next free), Archive `coach-store` tables + API, catalog seed, CRUD for exercises/templates/programs/sessions/sets/measurements, swagger, `hestia-coach.md` |
| **P2** | Records, e1RM, statistics endpoints, progression engine, stall detection, import/export |
| **P3** | MCP tools, `fitness` domain in Oracle classifier, readiness + adaptation engine, proposals → Hermes, agenda jobs, Themis settings |
| **P4** | WebUI pages + widgets on the plugin contract (needs the contract on main) |
| **P5** | Telegram commands polish, natural logging parsing, weekly review |

## 12. Acceptance criteria
1. I can build a scheda, start it on the phone, log a full session with the rest timer, and see "last time"
   values and next-time suggestions; nothing is lost on reload.
2. History, PRs and charts are correct against a hand-checked dataset (unit tests on records/e1RM/volume).
3. "Oggi sono a pezzi e ho 30 minuti" in chat → Oracle calls `coach_adapt_today` → a shorter, lighter plan
   with the rules explained; "ripristina" restores it.
4. A planned day not done triggers the evening Hermes message with buttons; Skip/Tomorrow work.
5. A Strong CSV export imports with mapped exercises.
6. Pages and widgets show up through the plugin contract and can be hidden per client.
7. Pytest (unit/api) tests for every engine rule (run by Marko/CI, not by Claude).

## 13. Open questions for Marko
1. Name: `Hestia-Coach` (domain modules use plain names like Scout) — or a Greek one (e.g. Heracles)?
2. Mostly strength/gym, or also cardio/sport sessions in v1?
3. Today's adaptation applies directly when I ask, permanent changes via Hermes confirmation — OK?

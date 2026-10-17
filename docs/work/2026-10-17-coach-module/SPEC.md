# SPEC — Hercules: gym coach, workout tracking & adaptive training module

| | |
|---|---|
| **Version** | 2.4 |
| **Source** | User via external chat (Claude Code cloud project, thread "Modulo Coach allenamenti") · 2026-10-17 |
| **Status** | Agreed with Marko 2026-10-17; implementation waits for the plugin contract on main (his call) |

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

A new **domain module `Hestia-Hercules`** (domain `fitness`, like Scout owns `real_estate`) that is a complete
strength-training tracker (reference apps: Strong, Hevy, JEFIT) with Hestia's extra: the assistant knows my
training and can **adapt today's workout** to how I feel, using rules that live in Hercules, not in Oracle.

## 2. Scope

### In (v1)
- Exercise catalog: seeded library (~120 common exercises, Italian names + English aliases) + my custom ones.
- Workout templates ("schede") grouping exercises with targets; folders; optional weekly **program**.
- Live workout logging (sets, weight, reps, RPE/RIR, set types, rest timer, supersets, notes).
- **Offline first**: the UI works with no connection (gym) and syncs when back online (§8.0).
- History, personal records, statistics, progress charts, body measurements.
- Progression engine (what to lift next time) and deload/stall detection — deterministic, in Hercules.
- Readiness check-in + **adaptation engine** (bad day, little time, pain, no equipment, skipped day).
- MCP tools for the assistant; a short on-demand context summary.
- Agenda integration (planned days, reminders via Chronos → Hermes); settings in Themis.
- WebUI pages + widgets through the plugin contract; Telegram quick logging via chat/commands.
- Import (Strong / Hevy CSV) and export (CSV / JSON).

### Out (v1, kept for later — see §10)
Cardio, running and other sports (Marko already tracks them with **Garmin**; Hercules is gym only), GPS, wearables / Health Connect sync, progress photos, exercise demo videos, nutrition,
social features, a mobile-native app.

## 3. Data model (stored in Archive, owned by Hercules)

Archive gets a pure-storage area `/api/hercules-store/*` (same pattern as settings-store / presence-store:
typed tables, CRUD + range queries, no business rules). All ids UUID, all rows `created_at/updated_at`,
soft delete (`archived`) so history never loses an exercise.

| Table | Key fields |
|---|---|
| `hercules_exercises` | name, aliases[], kind (`weight_reps` · `bodyweight_reps` · `weighted_bodyweight` · `assisted_bodyweight` · `reps_only` · `duration` · `distance_duration`), primary_muscles[], secondary_muscles[], stress_joints[] (for the pain rule), movement_pattern (squat · hinge · push_h · push_v · pull_h · pull_v · lunge · carry · core · isolation), equipment (`barbell` · `dumbbell` · `machine` · `cable` · `kettlebell` · `band` · `bodyweight` · `other`), unilateral, increment_kg (null = setting by equipment), notes, instructions, media_url, is_custom, archived |
| `hercules_templates` | name, folder, notes, color, estimated_minutes, position, archived |
| `hercules_template_items` | template_id, exercise_id, position, superset_group, rest_seconds, notes, **targets**: list of planned sets `{type, reps_min, reps_max, weight_kg?, rpe?, duration_s?, distance_m?}`, progression rule (`double` · `linear` · `rpe` · `none`) |
| `hercules_programs` | name, active, start_date, weeks (null = repeating), schedule `[{weekday or day_index, template_id}]`, deload_every_weeks? |
| `hercules_sessions` | started_at, ended_at, template_id?, program_id?, name, status (`active` · `done` · `discarded`), notes, readiness `{energy, sleep, soreness, stress, pain_areas[], free_text}`, adaptation_id?, bodyweight_kg?, perceived_effort (1–10) |
| `hercules_session_exercises` | session_id, exercise_id, position, superset_group, notes, replaced_from_exercise_id? |
| `hercules_sets` | session_exercise_id, position, type (`warmup` · `normal` · `drop` · `failure`), weight_kg, reps, rpe?, rir?, duration_s?, distance_m?, completed, completed_at |
| `hercules_measurements` | taken_at, kind (`bodyweight` · `body_fat` · `waist` · `chest` · `arm` · `thigh` · … custom), value, unit |
| `hercules_adaptations` | created_at, session_id?, input (readiness + request), output (modified plan), rule_trace[], accepted |

Derived data (PRs, e1RM, volumes) is **computed by Hercules**, not stored as truth; Hercules may keep a cache
table `hercules_records` (exercise_id, record kind, value, set_id, achieved_at) rebuilt from sets on any edit.
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

## 5. Hercules engines (deterministic, in Hercules — Oracle only calls them)

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
| repeated low energy (≥3 check-ins in 7 days) | flag "deload suggested" in the summary; the assistant brings it up (5.3) |

Adaptation is **a conversation with the assistant** (Marko, v2.0: "è più un feedback con cui parlo con
l'assistente"): I tell it how I feel, Oracle calls `hercules_adapt_today`, shows the adjusted plan with the
reasons, we talk it over, and it is applied to today's session when I agree in the chat. Reversible
("ripristina scheda originale"); it never changes the template.

### 5.3 Feedback and permanent changes (conversational, no Hermes proposals)
- After a workout (or any time) I give feedback in chat or in the finish screen: "troppo pesante", "spalla
  fastidiosa sulla panca", "mi annoia". `hercules_feedback` stores it (session/exercise, tags, free text);
  the engines use it next time (pain tag → pain rule; "too heavy" → no increment; boredom → swap suggestion).
- Engine findings (stall, deload due, repeated low energy, often-skipped exercise) are **not pushed**: they
  appear in `hercules_summary` / module context, so the assistant raises them when we talk about training.
- Changes to templates/programs are made only when I agree in the conversation; the assistant then calls
  `hercules_edit_template` / `hercules_edit_program`. Every edit keeps a revision (undo).

## 6. Assistant integration

### 6.1 MCP tools (`hestia_common.mcp_helpers.MCPTool`, domain `fitness`)
Read: `hercules_summary` (week at a glance, next workout, recent PRs, stalls, readiness trend — caveman text),
`hercules_next_workout`, `hercules_history` (range/exercise filter), `hercules_exercise_stats` (e1RM trend, PRs),
`hercules_search_exercises`, `hercules_templates`, `hercules_records`.
Write: `hercules_start_session`, `hercules_log_sets` (natural logging: "panca 80x8, 80x8, 77.5x7"), `hercules_finish_session`,
`hercules_checkin` (readiness), `hercules_adapt_today`, `hercules_restore_today`, `hercules_skip_day`, `hercules_postpone`,
`hercules_feedback`, `hercules_edit_template` / `hercules_edit_program` (only after my yes in chat), `hercules_log_measurement`.
Telegram-visible commands (group "Allenamento"): oggi, inizia, log, fine, check-in, salta, statistiche.

### 6.2 Context for the assistant
On demand, consistent with Themis ("Oracle knows itself on demand"): Oracle's classifier gets a `fitness`
domain (`preference_domains.py`) so these tools load only when relevant; `hercules_summary` is the compact
context. Shared contract `GET /api/module/context` (agreed with the sibling threads, §9): a ≤1-line caveman summary ("Allenamento: Push A oggi ·
3/4 sett. · PR panca 85 kg") a module may expose for the assistant's daily context.
Memory facts stay in Oracle/Archive memory; Hercules data stays in Hercules (no duplication into memory).

### 6.2b Training goals (same shape as Self care / Guardaroba)
- A goal is optional: `off` (default) or `{times, per: day|week|month}`.
- **Generic first**: "allenarmi 3 volte a settimana" counts any finished session. **Then optionally specific**:
  goals per template ("Gambe 1/settimana") or per muscle group ("schiena 2/settimana", counts sessions with ≥N hard
  sets for it). A program (§4.2) may set its goal automatically (days in the schedule per week).
- Progress shown everywhere the same way: "2/3 questa settimana", streak of periods met, history per period.
- **Fatto oggi in un tocco** from the WebUI Home (shared quick-log component proposed to the plugin thread):
  favourite templates as big chips. Tap → choose "Inizia" (live logging) or "Segna fatto" (records the session
  with the template's planned values, editable later, with Annulla). Also "fatto" in chat to the assistant.

### 6.3 Proactivity (minimal, all via agenda, no timers)
Marko's rule (same as Self care): reminders **off by default**, at most one live reminder, never stacking.
- `hercules.reminder` (agenda job, disabled by default): only when I'm **behind a goal** and haven't trained
  today; never during DND/night (presence); max 2 per week (setting). One Hermes message "Oggi: Push A · 55 min ·
  1/3 questa settimana" with my favourite templates as buttons (Inizia / Segna fatto); a still-unread reminder is
  replaced, not added (Hermes "One live reminder per thing", `Hestia-Hermes/hestia-hermes.md`): the event carries
  `replaces: "hercules.reminder"`, Hermes supersedes the open one on every client and adds the skip counter itself
  (Hercules text never counts skips); "Segna fatto" resolves it (`resolves: true` / `closes: "hercules.reminder"`).
  Hercules registers the matching Hermes subscription at startup.
- Missed days and the weekly picture are not pushed: they are in `hercules_summary` / module context, and the
  assistant mentions them when I talk to it ("ho saltato martedì, spostiamo?").
- Presence: Hermes applies `notify.level` (no logic in Hercules).

## 7. Settings (Themis, `settings_client.setting(...)`, no env)
`hercules.units` (kg/lb) · `hercules.rest.default_seconds` (90) · `hercules.increment.<equipment>` · `hercules.bar_weight`
(20) · `hercules.plates` (list) · `hercules.e1rm_formula` (epley/brzycki) · `hercules.week_start` (monday) ·
`hercules.goal` (off | {times, per}) · `hercules.reminder.max_per_week` (2) · `hercules.stall.exposures` (3) · `hercules.adapt.*` thresholds ·
`hercules.reminder.enabled` (false) · `hercules.reminder.time` · `hercules.skip_mode` (shift/keep) · `hercules.warmup.scheme`.
Env: only `HERCULES_PORT` / Hub URL (infrastructure).

## 8. Clients (UI through the plugin contract — implemented after that contract is on main)

Contract v2.0: `docs/work/2026-10-17-client-plugins/SPEC.md` §4 — Hercules ships its own UI as a Web Components
bundle (Lit + TS) in `Hestia-Hercules/ui/`, announced on Hub with `capabilities.ui_manifest`; the WebUI loads it
from a link. Sub-pages via `parent`, widgets with `params`. Live parts (active workout, rest timer) live in the
bundle and use `host.notify` for browser notifications; Hercules serves `started_at` / `rest_until`, the bundle ticks.

### 8.0 Offline first and sync
- Plugin contract v2.2 §4.5b: the WebUI is a PWA whose service worker caches shell, catalog and plugin bundles
  with their assets (per version). The bundle uses `host.online` + `online`/`offline` events and
  `host.store(name)` (IndexedDB namespaced `hestia.hercules.<name>`). Offline `host.api` fails with `offline`
  and queues nothing: the outbox and sync below are Hercules' own.
- Local store via `host.store` (IndexedDB): catalog, templates, program, settings snapshot, last 90 days of sessions/sets,
  records cache. The UI always reads/writes local first; the live workout never waits on the network.
- Every write is an **op** in a local outbox: `{op_id (uuid), entity, id (client uuid), action
  upsert|delete, fields, updated_at, device_id}`. All ids are generated on the client.
- `POST /api/hercules/sync {device_id, cursor, ops[]}` → Hercules applies ops **idempotently** (op_id
  dedupe), returns `{applied[], rejected[], changes_since_cursor[], cursor}`. Conflict rule: last write wins
  per row by `updated_at`; sets are rows of their own, so two devices rarely collide; deletes are tombstones.
- Sync runs on reconnect, on app open, and after finishing a workout; a small badge shows "N modifiche da
  sincronizzare". Records/stats are recomputed server-side after sync and pulled back.
- The assistant sees data only after sync (shown in the summary: "ultimo sync 2 h fa").

### 8.1 WebUI pages (always visible, per-client show/hide from the contract)
"Allenamento" with sub-pages: **Oggi** (next workout card, check-in, start; becomes the live workout),
**Schede** (templates + program editor), **Esercizi** (catalog + exercise detail), **Storico**,
**Progressi** (stats/charts), **Corpo**. Follows `DESIGN-SYSTEM.md`; side panels resizable with `<hx-resize>`;
mobile-first live workout (bottom-anchored controls, big tap targets, works one-handed, dark-friendly).

### 8.2 Widgets (for dashboards, also composable by Oracle)
Next workout · This week (sessions/target, streak, volume) · Recent PRs · Exercise progress chart
(param: exercise) · Muscle volume map (param: period) · Bodyweight trend · Active workout (timer + current set).

### 8.2b Quick actions (plugin contract v2.3 §4.2b, WebUI Home + Ctrl+K)
"Inizia allenamento di oggi" (dynamic `source`: label from the next workout, hidden if one is active) ·
"Riprendi allenamento" (active session) · "Registra peso corporeo" (`params`: weight, inline sheet, `undo`) ·
"Salta oggi" (`undo`).

### 8.3 Telegram
Commands from Hub discovery (6.1), natural-language logging through Oracle, the optional single reminder.
No rest timer on Telegram (WebUI only).

## 9. Shared with Guardaroba and Self care (to align, not to duplicate)
- Storage pattern: Archive `/api/<module>-store/*` typed tables, pure storage; the module owns logic (Hercules needs
  typed tables: stats query sets by date/exercise range; generic entities would mean loading everything).
- Plugin contract for pages/widgets (sibling thread owns it).
- `GET /api/module/context?budget=` → `{module, domain, updated_at, text}`, Hub tag `context`, built with
  `hestia_common.context_client.ModuleContext("hercules", "fitness", build_fn)` (written by the Guardaroba thread);
  `hercules_summary` returns the same text. Automatic inclusion in Oracle is a separate Oracle step.
- Photos/media (later, §10): the shared Archive media/blob store designed by the Guardaroba thread.
- Ports: Guardaroba 19017, Self care 19018, Hercules 19019.
- Changes are agreed in conversation with the assistant (no proposal cards); reminders off by default, one live max.
- Health/safety tone: Hercules never pushes through pain, no medical advice.

## 10. Later (not v1)
Progress photos (Archive file store) · exercise images/video · cardio sessions with GPS/heart rate ·
read-only Garmin summary (runs/cardio load) only as context for the gym plan · AI-generated programs from goals (Hercules rules + Oracle
wording) · nutrition link · 3D/heat muscle map.

## 11. Phases (each shippable alone)
| Phase | Content |
|---|---|
| **P1** | `Hestia-Hercules` service (FastAPI, Dockerfile, compose global, Hub registration, port **19019** — agreed with Guardaroba 19017 / Self care 19018), Archive `hercules-store` tables + API, catalog seed, CRUD for exercises/templates/programs/sessions/sets/measurements, swagger, `hestia-hercules.md` |
| **P2** | Records, e1RM, statistics endpoints, progression engine, stall detection, import/export |
| **P3** | MCP tools, `fitness` domain in Oracle classifier, readiness + adaptation engine, feedback, module context, optional reminder job, Themis settings |
| **P4** | UI bundle `Hestia-Hercules/ui/` (pages + widgets) on the plugin contract v2 (needs the WebUI runtime on main) |
| **P5** | Telegram commands polish, natural logging parsing |

## 12. Acceptance criteria
1. I can build a scheda, start it on the phone, log a full session with the rest timer, and see "last time"
   values and next-time suggestions; nothing is lost on reload.
2. History, PRs and charts are correct against a hand-checked dataset (unit tests on records/e1RM/volume).
3. "Oggi sono a pezzi e ho 30 minuti" in chat → Oracle calls `hercules_adapt_today` → a shorter, lighter plan
   with the rules explained; "ripristina" restores it.
4. Offline: with the network off I start, log and finish a whole session on the phone; back online it syncs
   with no duplicates and no lost sets (also two devices editing different sessions).
5. A Strong CSV export imports with mapped exercises.
6. Pages and widgets show up through the plugin contract and can be hidden per client.
7. Pytest (unit/api) tests for every engine rule (run by Marko/CI, not by Claude).

## 13. Decisions (Marko, 2026-10-17)
1. Name: **Hercules** (`Hestia-Hercules`; UI label "Allenamento").
2. Gym only (weights); cardio and sports stay on Garmin. Must work **offline** and sync when online.
3. Adaptation and changes are a **conversation with the assistant** (feedback), not Hermes proposals.

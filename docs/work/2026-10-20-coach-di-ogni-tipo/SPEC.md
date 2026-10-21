# SPEC — Coaches of every kind: one coach contract, one weekly plan, a nutrition module

| | |
|---|---|
| **Version** | 1.2 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 9 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0); routed by the project coordinator 2026-10-20 («iniziamo intanto, voglio che venga fatto tutto») |
| **Status** | Approved by Marko 2026-10-20 (answers in §12, v1.1); implemented C1 → C4 (v1.2 = paths as built) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the brainstorm): **coaches of every kind**, not only life: training,
nutrition, self care, finance, study… Every coach leans on a personal data set of Marko (the modules' data) and
**plans precisely** — e.g. a week of life + workouts from the Hygieia state, routines, Hercules adapted to the
calendar, diet and supplements (→ a new nutrition module). The plan lives in Chronos, Hermes delivers it.
**A common "coach" model reused by the modules, not a coach hand-written for each one.**
Earlier in the brainstorm: «giornata piena → allenamento corto o spostato nella finestra libera dell'agenda».

---

## 1. Today (verified in code, 2026-10-20)

- **Hercules** (fitness) already has goals `{times, per}`, a program (weekday or rotation), a time-limit adaptation
  rule (`fitness_adapt_today`: given minutes → shorter plan), readiness check-ins, deload/stall findings, an optional
  reminder (`hercules.reminder`, off by default). It does not know my calendar: "next workout" ignores how full the day is.
- **Hygieia** (self care) plans *today* only (states due/suggested/wait/blocked…), with goals per routine and
  never-same-day conflicts. No week view, no calendar.
- **Plutus** (finance) has budgets, monthly review, alerts. No weekly target.
- **Nutrition and supplements are not tracked anywhere.** Study/reading/other personal goals have no module.
- **Chronos** owns the calendar (Hecate → Archive sync every 15 min, `chronos.calendar_sync`), the assistant agenda
  (rules, jobs, windows, links, moves, user edits win) and presence (sleep window `assistant.sleep`). It has no
  notion of "free time" and places nothing.
- Every module exposes `GET /api/module/context` (one caveman line). Nobody combines them into a plan.
- Siblings started the same day and touching this: **layered reflection** (modules publish *signals*, Athena
  coordinates), **daily recap** (evening/morning message, every module its piece), **weather** (Hecate `weather_*`).

## 2. Goal

1. A **coach contract** every domain module implements with a few lines (shared helper in `hestia_common`): what I
   should do this week to stay on my goals, with the module's own rules and current state already applied.
2. A **weekly plan** built by Chronos (scheduling is its job) that fits every coach's needs into my real free time
   (calendar, sleep, presence), keeps it up to date when things change (push, not poll), and is delivered by Hermes
   with a short text written by Oracle.
3. **Coaches for every kind** that have data today: Hercules (training), Hygieia (self care, supplements included as
   products), Plutus (finance). Any later module joins with the same few lines. Nutrition tracking and a goals module
   are **out** for now (Marko v1.1: manual logging would not be followed); §8 is a study of how food data could arrive
   by itself instead.
4. The plan is discussed and changed **in conversation** with the assistant (same rule as Hercules: no proposal cards).

Vision check (open Jarvis): the contract is plain HTTP + JSON through Hub, so any external brain (Claude Code via MCP,
Codex…) sees the same needs and plan through tools; the planner is deterministic and works with no LLM at all
(Oracle only writes the text).

## 3. Roles (who does what — module boundaries)

| Step | Owner | Why |
|---|---|---|
| Know my goals, state, rules, what is due, shorter variants | each **domain module** (Hercules, Hygieia, Plutus) | domain logic stays in domain modules |
| Turn needs + free time into a week (generic constraint placement) | **Chronos** | scheduling = assistant agenda; Chronos already owns calendar, agenda and presence; it learns nothing about domains |
| Write the weekly message, answer "spostiamo gambe a giovedì" | **Oracle** (use case `chronos.coach`, tools) | Oracle is only the brain: it reasons and calls tools |
| Deliver the weekly message and change notices | **Hermes** | only outbound messenger |
| Weather for outdoor needs (when the weather dossier lands) | **Hecate** | idem |
| Cross-domain patterns over weeks ("after <6h sleep you skip the gym") | **Athena** (reflection dossier) | retrospective proposals, not planning |
| Settings | **Themis** | `chronos.coach.*`, `<module>.coach.*` |

Chronos stays generic (CLAUDE.md "core services stay generic"): it reads `minutes`, `count`, `days`, `time of day`,
`tags`, `priority`; it never reads "legs", "retinol" or "protein".

## 4. The coach contract (`hestia_common.coach`)

A module becomes a coach by mounting one helper and adding the Hub tag `coach` (added to Hub `ALLOWED_TAGS`).

```python
from hestia_common.coach import CoachRouter, Need
app.include_router(CoachRouter(module="hercules", domain="fitness", label="Allenamento",
                               needs=build_needs, fit=fit_need, placed=on_placed, review=review_week).router)
```

| Endpoint (module side) | Meaning |
|---|---|
| `GET /api/coach/needs?from=&to=` | `{module, domain, label, state, needs:[Need]}` — `state` is one caveman line (same text family as module context) |
| `POST /api/coach/fit {need_id, date, minutes}` | optional: a shorter variant that fits `minutes` → `{ok, minutes, title, note}` (Hercules = its time-limit rule; Hygieia = core steps only) or `{ok:false}` |
| `POST /api/coach/placed {week, items:[{need_id, key, start_at, end_at, kind}]}` | Chronos tells the module what landed where (Hercules makes "next workout" follow the plan) |
| `GET /api/coach/review?from=&to=` | `{done, missed, adherence, notes[]}` for the past week, from the module's own data. Same shape the reflection dossier calls *signals*: one producer, two readers (aligned with that thread, §11) |

**Need** (validated in the helper; unknown fields refused):

| Field | Meaning |
|---|---|
| `id` | stable per module (`workout`, `routine.<id>`, `supplement.<id>`, `goal.<id>`) |
| `title` | short Italian text, readable aloud ("Allenamento Push A") |
| `kind` | `block` = needs free time on the calendar · `slot` = a day + part of day, no reserved time (evening skincare, supplement at breakfast) · `target` = a number to reach, not placed (protein/day, budget left) |
| `count`, `per` | how many this week (`per: week`) or every day (`per: day`) |
| `minutes`, `min_minutes` | duration and the shortest acceptable variant (blocks only; `min_minutes` < `minutes` means `fit` is supported) |
| `days` | allowed weekdays (empty = any); `fixed_dates` for things bound to a date |
| `time_of_day` | `morning` · `midday` · `afternoon` · `evening` · `any` (+ optional `not_before`/`not_after` HH:MM) |
| `min_gap_days` | spacing between occurrences (Hygieia: `period_days // times`; Hercules: rest days) |
| `not_same_day` | tags it must not share a day with (`skin.acid` vs `skin.retinoid`, `legs` vs `long_walk`) |
| `with` | `{tag, relation: same_day\|day_after\|before\|after}` to place relative to another need, any module (supplement "after" `workout`) |
| `tags` | free labels for the relations above, plus `outdoor` (weather, later) and `effort:1..3` |
| `priority` | `must` · `should` · `could` — what is dropped first when the week is full |
| `reason` | one line: why it is due ("2/3 questa settimana", "settimana di scarico") |
| `link` | plugin page (`allenamento/oggi`) — every plan item opens its module |
| `value`, `unit`, `progress` | targets only ("proteine 120 g/giorno", "budget svago 40 € rimasti") |

Module helpers also get `coach.done(need_id, at)` / `coach.skipped(need_id, at, reason)`: when I log the thing in the
module (Hercules finishes a session, Hygieia marks a routine), the module tells Chronos and the matching plan item
becomes done/skipped. **Push**: Chronos never polls modules for completion.

## 5. The weekly plan (Chronos)

### 5.1 When it is built (agenda, push)
- Agenda job `chronos.coach_week` (owner chronos, weekly on the day before `themis.personal.week_start`, 18:00, editable
  or pausable in the agenda like every job — pausing it is how I stop the weekly plan; no on/off setting) →
  `POST /api/agenda/coach/week/run`.
- **Re-plan of the rest of the week** (only the affected days, never the past) when:
  - the calendar sync brings a new/moved event that overlaps a plan item (Chronos already runs the sync; it compares
    in the same call, no new job);
  - a module reports `skipped`, or a `must`/`should` item's day passed without `done` (checked lazily at the next
    re-plan or read, no timer);
  - a module's needs change (it calls `coach.changed()` → `POST /api/agenda/coach/report {module, event:"changed"}`; e.g. Hercules
    enters a deload week, Hygieia pauses acids);
  - I ask in chat or on the page ("rifai il piano", "mercoledì sono via tutto il giorno").
- Items I moved or edited are **never moved back** (agenda rule: user edits win).

### 5.2 Free time
Window per day = from `chronos.coach.day_start` (07:00) to `chronos.coach.day_end` (22:00), minus the sleep window,
minus my calendar events (Archive, synced from Hecate) with `chronos.coach.buffer_minutes` (15) around them, minus
busy blocks I add in chat ("mercoledì via"). Presence `busy`/`dnd` periods already in the agenda count as busy.

### 5.3 Placement (deterministic, `Hestia-Chronos/app/services/coach_planner.py`)
1. Collect needs from every service with Hub tag `coach` (through Hub; a module that does not answer is listed as
   "non raggiunto" and its last plan is kept — `[🔄] event=coach_needs_failed`).
2. Place `must`, then `should`, then `could`. For each need with `count` N: choose days that respect `days`,
   `min_gap_days`, `not_same_day`, `with`; spread evenly; prefer days with more free time for higher `effort`.
3. For a `block`: the first free gap of `minutes` in its `time_of_day`; none → the largest gap ≥ `min_minutes` and
   `POST fit` to the module (this is "giornata piena → allenamento corto"); still none → another allowed day.
4. Limits per day: `chronos.coach.max_blocks_per_day` (2) and `chronos.coach.max_minutes_per_day` (120).
5. `slot` needs get a day + part of day (no reserved time); `target` needs are only listed.
6. What does not fit goes to **unplaced** with the reason ("settimana piena: 2/3 allenamenti; mancano 45' liberi").
7. Same input → same plan (stable sort by priority, module, id), so re-plans move only what must move.

### 5.4 Storage
Plan items are assistant-agenda items (Archive `calendar_items`, `source=hestia`): `owner` = the module, type `event`,
key `coach.<iso-week>.<module>.<need_id>.<n>`, linked to a parent `coach.week.<iso-week>`; `params {coach:true,
kind, need_id, domain, minutes, variant, reason, link}`; status planned/done/skipped/missed. Nothing new in Archive.
The week's summary (targets, unplaced, last week's review, Oracle text) is `meta` of the parent item.

### 5.5 My own calendar
v1.1: the plan lives **only in Hestia** (page «Settimana», Telegram, chat). Mirroring blocks to a separate Google
calendar «Piano Hestia» (through Hecate, edits syncing back as my edits) stays a possible later step (Marko: «forse»);
nothing in C1–C3 depends on it.

## 6. Delivery and conversation

- **Weekly message** (Sunday evening by default): Chronos asks Oracle `/api/llm/generate` with use case
  `chronos.coach` (declared in its Hub registration, like `chronos.agenda`) → a short Italian text from: each coach's
  `state`, the placed plan, unplaced items, last week's review. Then Hermes `service.action_required`, domain `system`,
  target `owner`, `replaces: coach.week`, `_link` to the plan page; button **Apri il piano**. Oracle down → Chronos
  sends a fixed text built from the plan (`[🔄] event=coach_text_fallback`); the plan never waits for the brain.
- **Change notices**: only when a re-plan moves something of **today or tomorrow** that I did not move myself; one live
  message (`replaces: coach.change`). Everything else changes silently (it is on the page and in chat).
- **No new reminders**: the modules' own reminders (off by default, max per week) stay the only nudges; when on, they
  use the plan time ("Oggi alle 18:30: Push A").
- **Chat tools** (Chronos, domain `coach`, `<domain>_<verb>`): `coach_week` (plan + targets + unplaced),
  `coach_replan` (optional busy blocks / constraints for this week), `coach_move` (item → day/time),
  `coach_skip`, `coach_add_busy`, `coach_review` (last week). Oracle classifier gets the `coach` domain.
  Example: «questa settimana sono in trasferta mercoledì e giovedì» → `coach_add_busy` + `coach_replan` → Oracle
  answers with what moved.
- **Daily recap** (sibling dossier) reads today's/tomorrow's plan items from the agenda; the coach adds nothing there.

## 7. Coaches (adapters, each in its module)

### 7.1 Hercules — training
- Needs: `workout` blocks — `count` from the goal or the program; `minutes` = template estimate; `min_minutes` from the
  time-limit rule (default 30'); `days` from a weekly program, any day for a rotation; `min_gap_days` 1 when the
  previous session hit the same muscles; tags `effort:3` (`effort:2` in deload), `legs`/`push`/`pull` from the template.
  Target: none (training is time).
- `fit` → the existing time-limit adaptation (no new rule); the plan item shows "versione corta 35'".
- `placed` → "next workout" and the reminder follow the plan; `coach.done` on session finish, `coach.skipped` on
  `fitness_skip_day`.
- State: "Allenamento: 1/3 · scarico consigliato" (from `fitness_summary`).

### 7.2 Hygieia — self care
- Needs: one `slot` per routine with a goal (`time_of_day` from the routine slot morning/evening, `count` from the
  goal, `min_gap_days` from its spacing, `not_same_day` from conflict families), `daily` routines as `per: day` slots.
- `fit`: not needed (slots take no reserved time). `coach.done` from logs, `skipped` from Salta.
- Its own planner keeps deciding *today*; the coach only spreads the week so conflicts and spacing are visible ahead.
- **Supplements** (v1.1): they are Hygieia products of the existing category `integratore` (stock, finish prediction,
  shopping list, price already exist). What I take is **information for the assistant** (`selfcare_products`, module
  context line «Integratori: creatina, vitamina D»); nothing asks me to log each dose. A supplement put in a routine
  (e.g. «Mattina: vitamina D») becomes a `slot` like any routine; `with: workout same_day` is available for
  training-day-only ones.

### 7.3 Plutus — finance
- Targets: weekly budget left per category with a budget ("Svago: 40 € rimasti"). One optional `block`
  "Rivedi spese" (15') when uncategorized movements > `plutus.coach.review_threshold` (10). Review: budget kept/over.

### 7.4 Later coaches
Any future module (nutrition if food data ever arrives by itself, study, Scout visits…) is a coach by mounting
`CoachRouter`; nothing changes in Chronos.

## 8. Study: can food data arrive by itself? (no code)

Marko v1.1: «finché non riesco ad automatizzare la mia vita stile grande fratello non credo di seguirlo manualmente».
So no food diary. Deliverable of phase C4: a short evaluation (`/mnt/project-files/valutazioni/spesa-automatica.md`)
of the sources that need no daily effort, each judged on effort for Marko, data quality and module boundaries:
- grocery e-receipts and online orders by mail (supermarket apps, delivery) → already possible with the Iris push
  subscriptions (as Plutus does for PayPal);
- card payments already in Plutus (where, how much — not what);
- loyalty-card apps / digital receipts exports, if any Italian chain offers them;
- photo of the paper receipt in chat (one photo per shopping trip, Oracle reads it, as the Hype PDF).
Outcome: a recommendation for a future nutrition/pantry module, or "not worth it yet".

## 9. Dropped in v1.1
Hestia-Demeter (food diary, targets, meal plans) and Hestia-Mentor «Obiettivi» (study/reading goals): Marko
«troppo per il momento» / «lascia perdere». Ports 19021/19022 stay free.

## 10. Settings (Themis, declared with `settings_client.setting(...)`, no env)

`chronos.coach.day_start` (07:00) · `chronos.coach.day_end` (22:00) · `chronos.coach.buffer_minutes` (15) ·
`chronos.coach.max_blocks_per_day` (2) · `chronos.coach.max_minutes_per_day` (120) ·
`hercules.coach.time_of_day` (evening) · `hercules.coach.min_minutes` (30) · `plutus.coach.review_threshold` (10).
Week start = `themis.personal.week_start`.
No on/off switch for the coach: pausing the agenda job stops the weekly plan; a module with no goals emits no needs.
No new env variable.

## 11. Clients

- **WebUI** — Chronos plugin, new page **«La tua settimana»** (`settimana`) (order next to «Agenda di Hestia»): seven columns (phone: one
  day per screen, swipe), blocks with the module icon and colour, slots as small chips under the day, targets on top,
  «non entra» list with reasons, last week's review. Drag a block = my edit (`coach_move`); «Rifai il piano»;
  «Aggiungi impegno» (busy block). Widget **«Oggi nel piano»** for Home. Each module's Oggi page shows its next plan
  item ("Nel piano: giovedì 18:30"). Icons, never emoji; texts never name modules.
- **Telegram**: the weekly message with **Apri il piano**, command «settimana», and chat for changes.
- Swagger: coach contract (once, as a shared schema), Chronos `/api/agenda/coach/*`, module `/api/coach/*`.
- Siblings: reflection reads `GET /api/coach/review` as module signals (or the coach adopts their signal shape if it
  lands first — one format, decided by whichever SPEC Marko approves first); recap reads plan items; weather adds
  the `outdoor` rule in 5.3 when `weather_*` exists.

## 12. Decisions (Marko, 2026-10-20)

| # | Question | Answer |
|---|---|---|
| D1 | Who builds the week | **Chronos** («ok?» — taken as yes; a new core module was the alternative) |
| D2 | Where supplements live | Nutrition is dropped, so supplements stay where products already are: **Hygieia**, category `integratore`, as information (§7.2). Reversible if a nutrition module comes later |
| D3 | Plan in Google Calendar | «forse?» → **not now**, plan only in Hestia (§5.5) |
| D4 | Study/reading goals module | «lascia perdere» → **dropped** |
| D5 | Nutrition depth | «troppo per il momento» → **no food diary**; study automatic food data instead (§8) |

## 13. Phases (each shippable alone)

| Phase | Content |
|---|---|
| **C1** | `hestia_common.coach` (Need, CoachRouter, done/skipped/changed client) + Hub tag `coach` + swagger; Chronos planner, `/api/agenda/coach/*`, plan items, job `chronos.coach_week`, weekly message (Oracle text + fallback) via Hermes, tools `coach_*`, `coach` domain in Oracle classifier; adapters Hercules + Hygieia (supplements as information) |
| **C2** | Re-plan triggers (calendar sync overlap, skipped/missed, needs-changed), change notices, WebUI page «Settimana» + widget, module Oggi pages show their plan item |
| **C3** | Plutus adapter; weather `outdoor` rule if the weather dossier is on main; signal format aligned with reflection |
| **C4** | Study §8 (automatic food data) — document only |
| **C5** | Tests green, cloud bench run of the chain, docs everywhere, root CHANGELOG, PR merged when CI is green |

### 13.1 As built (v1.2)
- Chronos endpoints live under its plugin prefix: `GET /api/agenda/coach/week|today|review`, `POST /api/agenda/coach/replan`,
  `/week/run`, `/report` (module events done/skipped/changed), `/items/{key}/move`, `/items/{key}/skip`, `/busy`,
  `DELETE /api/agenda/coach/busy/{key}`. Modules keep `/api/coach/needs|fit|placed|review`.
- Weather `outdoor` rule: the weather dossier is not on main yet → deferred to that thread (the rule is a tag on the
  need plus one filter in the planner; nothing else changes).
- Study C4: `docs/work/2026-10-20-coach-di-ogni-tipo/STUDIO-spesa-automatica.md` (copy in
  `/mnt/project-files/valutazioni/spesa-automatica.md`): not worth a nutrition module yet.

## 14. Acceptance criteria

1. With Hercules 3×/week, two Hygieia routines with a conflict and a full Tuesday in Google Calendar, the Sunday
   plan puts three workouts on non-consecutive free evenings, never on Tuesday, and never the two routines on the
   same day; same input twice → identical plan (unit tests on the planner).
2. A day with only 40 free minutes gets the short workout from Hercules' `fit`, with "versione corta" in the plan.
3. A new calendar event over Thursday's workout (after the 15-min sync) moves it to the next free allowed day; if it
   is today or tomorrow I get one Hermes notice, otherwise nothing.
4. Finishing a session in Hercules marks the plan item done with no polling; skipping re-plans the rest of the week.
5. A block I move by hand (WebUI or chat) is never moved back by a later re-plan.
6. Oracle down → the weekly message still arrives with the fixed text.
7. A supplement in a routine with `with: workout same_day` shows on the days the plan has a workout; the assistant
   answers «che integratori prendo?» from Hygieia without any logging.
8. Chronos code contains no domain words (test: the planner runs on synthetic needs only).
9. Pytest (unit/api) for the contract helper, the planner rules and every adapter; CI green.

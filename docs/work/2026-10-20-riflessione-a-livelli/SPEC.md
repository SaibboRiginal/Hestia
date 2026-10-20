# SPEC — Layered reflection: module signals → Athena coordinator, system health apart

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | User via external chat (brainstorm 2026-10-19, item 5 of the final list in `/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md`, sections 0, 4 and 5) → project thread «Riflessione a livelli» |
| **Status** | Draft, waiting for Marko's approval (no code before it) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## Why (Marko's words, summarised)
Not everything in Athena. Reflection works in layers, like a coordinator with threads:
1. every module judges **its own** data with its own competence (coach: progress and consistency; self care: routine
   adherence; spending: budget) and publishes short **signals**, computed deterministically;
2. Athena is the layer above: proactive and autonomous (woken by the agenda), it reads the signals (never the raw
   data), looks for the **links between domains** («weeks with 3 workouts → better diary scores») and asks a module for
   details when a signal deserves it (extension of `/api/module/context`); every thought goes through Oracle;
3. Hestia's observation of itself (system health) stays a **separate track**, so it never mixes with Marko's life.
Athena only proposes: observations to Marko through Hermes, setting changes through Themis. Nothing acts by itself.

## What exists today (checked on main 0ca846d)
- Athena has one loop (`runtime.py`): observe (Hub services, Argus health and errors, Archive entity counts per domain,
  Metis weak spots, settings, presence) → one Oracle call (`athena.strategia`) → relevance gate → Hermes / Forge /
  Themis proposal → thinking record. Domain observation is only **entity counts and titles**: Athena knows nothing of
  workouts, routines or spending.
- Domain modules (Hercules, Hygieia, Plutus, Wardrobe) already serve `GET /api/module/context?budget=` → one caveman
  line (tag `context`, capability `context_endpoint`). Nobody reads it yet besides the bench test.
- Hercules already computes stall / deload / missed days in `summary()`; Hygieia adherence and alerts; Plutus budget
  pace and recurring; Wardrobe forgotten items. Signals reuse these, no new judging logic in Athena.
- Archive has the generic module store (`module_store.py`, rows + cursor) used by every newer module.

## Goal
Two tracks in Athena, fed by one new shared contract.

### A. Signals (shared contract, `hestia_common.signals_client`)
A **signal** is a short deterministic fact a module publishes about its own domain:

| Field | Meaning |
|---|---|
| `key` | stable id inside the module (`stall:panca_piana`, `budget_pace:month`); module+key = row id, so republishing **updates** instead of duplicating |
| `kind` | `trend` · `streak` · `anomaly` · `goal` · `milestone` |
| `severity` | `info` · `attenzione` · `alta` |
| `text` | one caveman Italian line, user-safe (no module names) |
| `metrics` | small dict of numbers behind the text (optional) |
| `period` | the day or ISO week it refers to |
| `expires_at` | default 7 days; `retract(key)` closes it earlier (e.g. stall solved) |

Plus **weekly metrics**: numeric series a module exposes for correlation, one value per ISO week
(`fitness.sessions`, `fitness.avg_energy`, `selfcare.adherence`, `selfcare.journal.<metric>`, `finance.spent`,
`finance.spent.<category>`, `wardrobe.worn`). Stored as signals of kind `metric` with `period=YYYY-Www`.

Helper API (same style as `mail_client` / `reminders`):
`Signals(module, domain).publish(key, text, kind, severity, metrics=None, period=None, ttl_days=7)`,
`.retract(key)`, `.metric(name, week, value)`, `.register_evaluation(path, hour)`.

Where they are stored: Archive `signals-store` (a new instance of the generic module store, no new DB code). Each
module writes only its own rows; Athena reads with the store cursor (only what changed since last cycle).

When modules publish (**push, never poll**):
- on write, where it is natural (session logged → PR milestone, stall; expense saved → budget pace);
- once a day for time-based facts (missed days, nothing worn for 60 days, week closed → weekly metrics), with an agenda
  job `<module>.signals` registered through `register_evaluation` (default evening, editable in the agenda like every
  job; Chronos rings `POST /api/<prefix>/signals/run`).
- A signal with `severity=alta` also rings Athena (`POST route/athena/api/athena/signals/ring`): the life track runs at
  the next moment the agenda window and presence allow, instead of waiting for the evening.

### B. Details on demand (extension of `/api/module/context`)
`GET /api/module/context?budget=<chars>&topic=<signal key>` → same response `{module, domain, updated_at, text}`, but
the text explains **that** signal (e.g. last 4 exposures of the stalled exercise, the categories driving the budget
pace). Without `topic` nothing changes. A module that does not know the topic answers its normal line. Swagger and
ARCHITECTURE rule 5 updated.

### C. Athena life track («Vita»)
New cycle in Athena, separate from the system loop:
1. **Read** active signals + new weekly metrics from Archive (cursor).
2. **Link (deterministic)**: for every pair of weekly series from **different** domains with ≥ `min_weeks` paired
   weeks, Pearson correlation at lag 0 and 1 week; keep `|r| ≥ min_correlation`. Computed in Python, not by the model.
3. **Choose topics**: the strongest links + `attenzione`/`alta` signals, at most `max_topics`; skip anything already
   told within `repeat_days` (dedup by signal keys / series pair).
4. **Ask details**: `/api/module/context?topic=` for each chosen signal (budget `detail_budget`).
5. **Think**: one Oracle call with a new use case `athena.riflessione` (chain `potente`) and a caveman prompt: signals,
   links with numbers, details → at most `max_per_day` observations in the existing `AZIONE/TIPO/...` format, kinds
   `observation` (a fact + why it matters, never an order) or `setting` (one personal module setting, e.g. weekly
   workout goal, proposed through Themis as today).
6. **Gate** with the same relevance score and threshold; accepted observations go to Hermes as
   `athena.focus_brief` with `_link` to the module page the topic belongs to (user text names the domain:
   «Allenamento», «Spese», never the module).
7. **Record**: thinking record with `track: "vita"`, the signals and links used, so «Pensieri» shows why.

When: agenda window `athena.reflection`, default daily 20:00–22:00, editable / skippable / pausable in the agenda
(pause = Athena silent on life, Marko's decision, no fallback), plus the `alta` ring. Respects presence (`work.light`)
and the idle gate like today. No on/off setting (rule: no feature switches).

### D. System track («Sistema») stays as it is, minus domains
The current loop keeps services, errors, quality, settings, Forge. Domain entity counts leave its prompt (they now come
as signals to the life track). Its records get `track: "sistema"`. Nothing else changes.

### E. Clients
- Page **Pensieri** gets a «Vita / Sistema» switch on the cycle list; a life cycle shows signals → links (with r and
  weeks) → details asked → observations and gate. Stroke icons, no emoji.
- New page **Segnali** (Athena plugin, order 131): active signals grouped by domain with severity tone, and the weekly
  series of each domain as small sparklines; empty state explains signals appear as modules collect data.
- MCP tool `athena_signals(domain?, limit?)` read-only, clients `ui` + `external`, so the assistant in chat can answer
  «com'è andata la settimana?» from the signals.

### F. Settings (Themis, `athena.reflection.*`, all live)
| Key | Default | Notes |
|---|---|---|
| `athena.reflection.max_per_day` | 2 | observations sent per day |
| `athena.reflection.max_topics` | 4 | topics per cycle |
| `athena.reflection.min_weeks` | 6 | paired weeks before a link counts |
| `athena.reflection.min_correlation` | 0.6 | minimum |r| (advanced) |
| `athena.reflection.repeat_days` | 14 | same topic not repeated before (advanced) |
| `athena.reflection.detail_budget` | 600 | chars asked to a module per detail (advanced) |
Signal TTL and evaluation hour are not settings: TTL is the module's call, the hour is the agenda job.

## First signals per module (deterministic, from logic that already exists)
| Domain | Signals | Weekly metrics |
|---|---|---|
| Allenamento (Hercules) | stall per exercise, deload suggested, planned days missed in a row, new PR (milestone), week behind goal | sessions, volume, avg check-in energy |
| Self care (Hygieia) | adherence drop vs previous 4 weeks, goals behind, routine streak | adherence %, journal metric averages |
| Spese (Plutus) | budget pace over, unusual week vs 8-week median, new subscription found | spent, spent per top category |
| Guardaroba (Wardrobe) | items forgotten > 60 days, laundry backlog | worn count |
Scout and the rest: none in v1 (can add later with the same helper).

## Out of scope (v1)
- Calendar busyness as a series (valuable for «busy weeks → fewer workouts»; needs a calendar metric from the calendar
  owner: later, own small SPEC).
- Sleep / mood tracking: not tracked anywhere today (Hygieia's journal is per body area). Links appear as soon as a
  module publishes such a series.
- Daily recap (sibling thread «Recap della giornata») owns Athena's `app/core/recap.py` and the per-module contract
  `GET /api/module/recap` (`hestia_common.recap`); this work does not touch them. Later the life track may add a
  «da tenere d'occhio» line to the recap through that contract. Coaches (sibling thread) may read the same signals;
  the contract is shared, the features are theirs.

## Acceptance criteria
1. Logging a workout that makes an exercise stall publishes one `stall:<exercise>` signal; logging a better set
   retracts it. Republishing never duplicates rows.
2. With 8 weeks of fake data where workouts and adherence move together, the life cycle finds the link (r and weeks in
   the record), asks both modules for details, and sends at most `max_per_day` observations through Hermes; the same
   link is not sent again within `repeat_days`.
3. An `alta` signal makes a life cycle run inside the window without waiting for the evening; outside the window or
   with the window paused it waits / stays silent.
4. The system cycle prompt contains no domain data; life cycle prompt contains no service / error data.
5. Athena never writes to a module and never changes a setting: only Hermes notices and Themis proposals.
6. Oracle down → life cycle recorded with outcome `failed`, nothing sent, no static fallback text.
7. `athena_signals` returns the active signals; Pensieri and Segnali render on desktop and phone, light and dark.
8. Unit tests for helper, correlation, dedup, each module's signals; bench run (`python tools/cloud_test.py all`) green.

## Phases
- **P1** `hestia_common.signals_client`, Archive `signals-store`, `topic` on `/api/module/context`, swagger, ARCHITECTURE rule.
- **P2** Signals + weekly metrics + `<module>.signals` job in Hercules, Hygieia, Plutus, Wardrobe (+ `topic` details).
- **P3** Athena life track (read, correlate, topics, details, `athena.riflessione`, gate, Hermes, records, ring) and
  system track cleanup.
- **P4** Plugin: Pensieri Vita/Sistema, page Segnali, MCP `athena_signals`.
- **P5** Docs (athena + 4 module md, shared md, swagger, ARCHITECTURE, AI-GUIDE, readme), bench run, PR, merge.

## Design decisions
- Signals live in Archive, not in each module behind an endpoint: Athena reads one place with a cursor (push), and the
  recap/coach threads can reuse them without asking every module.
- Correlation is deterministic: the model only words and weighs, it never invents numbers.
- Details are asked, not stored: modules keep raw data private to their domain; Athena sees only what the module
  decides to say about one topic.
- One Oracle call per cycle per track, as today.

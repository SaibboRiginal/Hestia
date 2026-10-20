# SPEC — Daily recap («com'è andata, cosa c'è domani»)

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 6 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0 and §4 «Digest = recap della giornata»); routed by the project coordinator 2026-10-20 |
| **Status** | Draft, waiting for Marko's approval (no code before it) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (brainstorm, Italian): «la sera (o la mattina) un messaggio solo con com'è andata (agenda fatta/saltata,
allenamento, routine, spese, notifiche importanti) e cosa c'è domani. Ogni modulo fornisce il suo pezzo, Oracle scrive
il testo, Chronos dà l'orario, Hermes lo consegna.» Vision check: an open personal "Jarvis"; any module, present or
future (weather, coaches, voice), must be able to add its piece without touching the recap code.

---

## 1. Today (verified in code, 2026-10-20)

- Hermes already sends one grouped message, «Mentre riposavo», but only for notifications **held** by the presence
  level, when the level relaxes (`Hestia-Hermes/src/modules/notifications.py`, `POST /api/notifications/release-held`).
  It is a fixed template, no LLM, and says nothing about the day.
- Domain modules (Hercules, Hygieia, Wardrobe, Plutus) expose `GET /api/module/context?budget=` → one short caveman
  line for the assistant's chat context (ARCHITECTURE «Module context»). It is "state now", not "what happened on day X
  and what is planned for day Y". Scout, Chronos and Hermes have none.
- Chronos knows the assistant agenda (`/api/agenda`, with `status`, `skipped`, `run`), the user's calendar
  (`/api/calendar/agenda`) and the runs (`/api/agenda/runs`).
- Athena is the proactive layer: it observes modules, asks Oracle, emits briefs to Hermes, archives what it thought.
  The sibling thread «Riflessione a livelli» is reshaping Athena (module signals + Athena as coordinator).

## 2. Goal

One message a day (evening by default, morning on request) that says, in a few lines, how the day went and what is
on tomorrow, written by the model from facts the modules give, delivered by Hermes to every client.

Out of scope: weekly/monthly reports (later, same contract with `span`), voice reading of the recap (Voce module will
be able to read any notification), coaching advice (item 9: coaches can add a piece later through the same contract).

## 3. Design

### 3.1 Who does what (module boundaries)

| Step | Owner | Why |
|---|---|---|
| When | **Chronos**: agenda job `athena.recap.evening` (default 21:30, daily), visible and movable in the calendar | Scheduling = agenda, never a timer |
| Facts of each domain | **each module**, deterministic, no LLM: `GET /api/module/recap` | each module only knows its own data |
| Collect + ask the text | **Athena** (new file `app/core/recap.py`, independent from the reflection loop) | Athena is already the proactive layer that gathers from modules and speaks through Hermes; no new service |
| Write the text | **Oracle**, `POST /api/llm/generate` with use case `athena.recap` (chain *veloce*) | only Oracle calls models |
| Deliver | **Hermes** event `athena.recap`, every client | the only outbound messenger |
| Store | **Archive** (Athena's domain, one row per recap with the pieces and the text) | the only DB owner |

Alternative considered: a new tiny module only for the recap. Rejected: it would duplicate Athena's "gather, think,
speak" job (organ model rule 10).

### 3.2 Module piece contract (new, global)

`GET /api/module/recap?day=YYYY-MM-DD&next=YYYY-MM-DD` → JSON, deterministic, fast (< 2 s), never calls Oracle:

```json
{"module": "hercules", "title": "Allenamento", "icon": "dumbbell", "emoji": "🏋️", "order": 30,
 "done":  [{"text": "Push A: 5 esercizi, 18 serie, panca 80×5 (record)", "tone": "success"}],
 "missed":[{"text": "Stretching saltato", "tone": "warning"}],
 "next":  [{"text": "Pull B alle 18:30", "at": "2026-10-21T18:30:00+02:00"}],
 "note": "3 allenamenti su 4 questa settimana"}
```

- Every list is optional; a module with nothing to say answers `{"module": "...", "empty": true}`.
- `title` is a generic domain word («Allenamento», «Cura di sé», «Spese», «Agenda», «Case»): user texts never
  name modules.
- Advertised by Hub capability `recap_endpoint: "/api/module/recap"`. Athena discovers pieces from the Hub registry,
  so a new module (weather, coaches, nutrition…) joins the recap by exposing the endpoint, with no change in Athena.
- Shared helper `hestia_common.recap` (piece builder, capability, date parsing) so modules write only their facts.

### 3.3 First pieces (this dossier)

| Module | `done` / `missed` (day) | `next` (next day) |
|---|---|---|
| Chronos | user calendar events of the day; assistant agenda tasks done / skipped / failed (jobs only if failed) | calendar events + assistant tasks of tomorrow |
| Hermes | important notifications of the day still open (actions waiting), count of the rest | — |
| Hercules | workout done (volume, records) or planned-and-missed | planned workout |
| Hygieia | routines done / missed, products used | routines due tomorrow |
| Plutus | spent today by category, budget alerts | recurring payments due tomorrow |
| Wardrobe | outfit worn (if logged) | outfit planned / laundry list |
| Scout | new listings evaluated, best match | viewings in the calendar come from Chronos |

Sibling dossiers plug in through the same endpoint: **weather** (Hecate, tomorrow's forecast) and **reflection**
(Athena may add one «da tenere d'occhio» line from the module signals). Coordinated through the project coordinator.

### 3.4 Writing the text

- Athena calls every `recap_endpoint` through Hub in parallel (timeout per piece `athena.recap.piece_timeout_seconds`,
  default 5); a failed piece is skipped and logged `[🔄] event=recap_piece_failed module=…`.
- Prompt in caveman style: pieces as compact lines, sorted by `order`, plus the style setting. Output in Italian,
  HTML for Telegram (`<b>` section headers), under `athena.recap.max_chars`.
- Model unavailable (Oracle down, chain exhausted): **deterministic fallback**, the same pieces rendered as a plain list
  (title + done/missed/next). The recap is never lost, only less pretty (`[🔄] event=recap_fallback_template`).
- Nothing to say from any module → no message (logged `event=recap_empty`), so a quiet day does not produce noise.

### 3.5 Delivery

- Hermes event `athena.recap`, level `info`, `replaces: "athena.recap"` (only the latest recap stays live in clients),
  `_link: {module: "athena", page: "recap"}`, `emoji` for Telegram and `icon`/`tone` for the WebUI.
- Presence is respected by Hermes as usual: if the user is resting the recap is held and arrives in «Mentre riposavo».
- Telegram: HTML message. WebUI: notification + the page below.

### 3.6 Settings (Themis, owner `athena`) — tunables only, no on/off switch

| Key | Type / default | Meaning |
|---|---|---|
| `athena.recap.style` | enum `asciutto` · `amichevole` (default `amichevole`) | tone of the text |
| `athena.recap.max_chars` | int 900 | length cap |
| `athena.recap.piece_timeout_seconds` | float 5 | per-module wait |

The time is the agenda job (move it in the calendar); stopping the recap = pausing the job (user decision, no fallback).

### 3.7 Morning variant and on-demand

- Agenda template «Recap» (calendar wizard «Da un modulo…») with field `momento` = `sera` | `mattina`: the user can add
  a morning recap (yesterday in brief + today) or a second one. The evening job is the only default.
- Tool `recap_today` (`clients` include the chat and external AIs): "fammi il recap" in chat composes it now and
  returns the text (no Hermes delivery, it is a chat answer).
- WebUI quick action «Recap adesso» and Athena plugin page **Recap**: the history (day, text, pieces collapsible),
  stroke icons only, no emoji.

### 3.8 API changes

- New on each piece module: `GET /api/module/recap` (+ capability `recap_endpoint`).
- Athena: `POST /api/athena/recap` `{day?, momento?, deliver?}` → `{text, pieces, delivered}` (agenda job, tool,
  quick action); `GET /api/athena/recaps?limit=` (page).
- Swagger, `docs/ARCHITECTURE.md` (new «Module recap» contract next to «Module context»), every touched `hestia-*.md`.

## 4. Acceptance criteria

1. With the stack up, the evening job produces **one** Hermes notification with sections from every module that had
   something to say, in Italian, without module names, under `max_chars`.
2. A module down or slow does not block the recap; it is missing and logged.
3. Oracle down → the template fallback is delivered.
4. Moving the job in the calendar moves the recap; pausing it stops it; the morning template works.
5. A new module exposing `/api/module/recap` appears in the next recap without changes in Athena (test with Dummy).
6. Tests (unit/api) for the helper, Athena collector/fallback/empty day, each piece; cloud bench run with screenshots.

## 5. Phases

- **R1** — `hestia_common.recap`, contract in ARCHITECTURE + swagger, Athena collector, prompt, fallback, Archive
  rows, Hermes delivery, agenda job, use case `athena.recap`, settings.
- **R2** — pieces: Chronos, Hermes, Hercules, Hygieia, Plutus, Wardrobe, Scout.
- **R3** — tool `recap_today`, agenda template (morning), quick action, Athena plugin page «Recap».
- **R4** — docs sync, tests, cloud bench run, PR.

## 6. Questions for Marko

1. Default time of the evening recap: **21:30** (recommended) or another?
2. Morning recap as well by default, or only on request from the calendar (recommended: only on request)?
3. Quiet day: send nothing (recommended) or a one-liner «giornata tranquilla»?

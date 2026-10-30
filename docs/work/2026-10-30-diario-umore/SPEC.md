# «Umore»: Hestia remembers how Marko feels, over time, like a coach

| | |
|---|---|
| **Version** | 2.0 |
| **Source** | user via Project thread (Marko 2026-10-30, in the real-AI test thread: «magari che si ricordi del mio mood e ci sia uno storico tipo coaching non sarebbe male? tipo un modulo diario? questo è una feature nuova separata»; 2026-10-30: «un modulo suo ma non chiamarlo diario... non voglio dover confermare ogni volta l'assistente deve essere intelligente») |
| **Status** | Approved by Marko 2026-10-30 — implementing |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
## 1. Today (verified in code, main `e678d9e`)

- **Memory refuses moods on purpose.** `memory_preferences_template` (Oracle `prompt_config.py`) rule 2c: «Stati del
  momento (stanco oggi, stasera pizza) -> NONE». Right for memory (durable facts), but the mood is then lost.
  `_quick_answer` also blocks answers that *claim* to have recorded it (bench 2026-10-30: «oggi sono stanco» →
  «Ho registrato la stanchezza…» was a lie). So today: Hestia answers kindly and forgets.
- **Hygieia already has a diary**, but it is a *self care* diary: 1–5 scores per body area (viso, capelli, barba,
  corpo…, `catalog.METRICS`), tags (`stress`, `dormito poco`, `ciclo`…), plus two special areas:
  - `giornata` — the spoken evening diary (brainstorm B9): after the evening recap the button «Racconta la
    giornata» opens `selfcare_diario_voce`, Echo transcribes, the text becomes one entry; signal `diario` gives it to
    Reflection.
  - `sonno` — one entry per night from the watch (B10, Hecate feed `wearable.daily`).
  - Its Hub `when_to_use` already says «sonno, umore», but there is **no mood metric**: area `*` only has «Stato
    generale». Nobody records mood, energy or stress as such, and nothing shows a mood trend.
- Recap (`hestia_common.recap`), Reflection signals (`signals_client`), Coach contract (`hestia_common.coach`),
  agenda (`agenda_client`), voice (`voice_client`), `module_kit` are all there to build on.

## 2. Goal

Hestia keeps a **history of how Marko feels** (mood, energy, stress, a few words why) and uses it like a coach:
- it **notices** when he says how he feels in a normal chat («oggi sono stanco», «giornata pesante», «sono carico»)
  and writes it down — quietly, truthfully, undoable;
- he can also **log in one tap** (Home, Telegram, evening recap) or **tell the day** by voice;
- he can **see** it: today, a month calendar, the trend, what goes with good and bad days (sleep, training, weather,
  busy calendar);
- the assistant **uses** it with care: «ieri eri a pezzi, oggi come va?» in the evening recap, a lighter week
  proposed when energy has been low for days — always as a proposal, never nagging.

Not a goal: diagnosis, therapy, scores about mental health, alerts to anyone but Marko.

## 3. Scope and design

### 3.1 Where it lives (Marko: «un modulo suo ma non chiamarlo diario»)

New module **Hestia-Psyche**, people's name **«Umore»** (never «diario»), port **19029**, Archive store
**`mood-store`**, Hub tag/domain **`mood`**, tools `mood_*`, area «Umore» (Telegram/WebUI), page decade **240s**.
Hygieia keeps its self care diary unchanged (body areas, the spoken «Racconta la giornata», sleep from the watch):
two different jobs, two modules (R1). Nothing moves.

### 3.2 Data (Archive `mood-store`)

- kind `mood`, one check-in: `{date, at, mood 1–5, energy 1–5|null, stress 1–5|null, labels[], causes[], note,
  quote, source: chat|tap|webui|telegram|external}`. `ref_id` = date (YYYY-MM-DD) for range reads.
  - `labels` (closed vocabulary, module options): stanco, carico, sereno, contento, motivato, annoiato, nervoso,
    ansioso, triste, giù, arrabbiato, malato.
  - `causes`: lavoro, sonno, persone, salute, sport, soldi, casa, tempo libero, meteo.
  - `quote` = Marko's own words (max 200 chars) when it came from chat, so he sees *why* it was recorded.
- Day summary is **computed**, never stored: last mood of the day + min/max + labels union.
- Export/import (`.hestia`, `hestia_common.transfer`) and the Drive backup (Archive) include it with no new path.

### 3.3 How the assistant records (Marko: «non voglio dover confermare ogni volta»)

No confirmation, ever. The model may be a 9B local one, so the rule is small, deterministic first, and fails towards
NOT recording.

1. **Explicit** («segna che oggi sono giù», «come mi sono sentito questa settimana?») → tools `mood_log` /
   `mood_history`, normal tool flow.
2. **Quiet capture from any chat message** (Oracle, after the answer, in the background step that already does the
   memory extraction):
   - **Deterministic gate** (`mood_intent.mood_clauses`, no model): the message is split into clauses; a clause
     counts only when it has a first-person present cue (sono, mi sento, sto, oggi, stamattina, stasera, che…) **and**
     a word of the mood lexicon, and is not a question («perché sono sempre stanco?»), not hypothetical («se fossi…»),
     not negated («non sono stanco»), not about someone else («Luca è stanco» has no first-person cue). A statement
     inside a request still counts («sono stanco, cosa mangio stasera?»).
   - Gate passed → one short caveman prompt (use case `oracle.mood`, chain `veloce`) returns
     `{"mood":1-5,"energy":1-5|null,"stress":1-5|null,"labels":[…],"causes":[…]}` or `NONE`. Labels/causes outside the
     vocabulary are dropped; numbers clamped. Model unreachable or garbage → the **lexicon guess** of the gate is used
     (so a dumb or offline model still records «stanco»); model says `NONE` → nothing.
   - Oracle hands it to the module that declares the Hub capability `mood_capture_endpoint` (no module name in
     Oracle), source `chat`, quote = the clause. The module **merges** a capture within
     `psyche.capture.merge_minutes` (Themis, default 120) of the previous chat capture of the same day.
   - The reply never claims it (truth rule); after the answer the client gets a quiet notice «Umore segnato:
     stanco» (same channel as «Ricordato»). No question, no button to confirm.
3. **«Non segnarlo» / «togli l'umore» / «non è vero, sto bene»** → the gate recognises the undo phrase and Oracle
   calls the module's `…/capture/undo` (removes today's last chat capture); notice «Umore tolto».
4. Memory rule 2c stays: moods never go to long-term memory. Patterns are computed (§3.5), never written as facts.

### 3.4 Tools (domain `mood`, clients ui/telegram/external)

| Tool | What |
|---|---|
| `mood_log` | mood 1–5 (required), energy, stress, labels, causes, note, date |
| `mood_today` | today's check-ins and summary |
| `mood_history` | last N days (default 30): per-day summary, averages, trend |
| `mood_insights` | the coaching view in plain sentences (§3.5) |
| `mood_delete` | one entry by id, or `last=true` |

REST for the plugin and the capture: `GET/POST /api/mood`, `PUT/DELETE /api/mood/{id}`, `GET /api/mood/today`,
`GET /api/mood/history`, `GET /api/mood/insights`, `POST /api/mood/capture`, `POST /api/mood/capture/undo`,
`GET /api/mood/options`, `POST /api/mood/signals/run`, `POST /api/mood/checkin` (agenda job), `GET
/api/module/context`, recap `GET /api/module/recap`.

### 3.5 Coaching (deterministic facts; Oracle only writes words)

- **Trend**: 7/30-day mean of mood and energy vs the previous period; best/worst weekday; most frequent labels and
  causes; good days (≥ 4) vs bad days (≤ 2) count. With fewer than `psyche.insights.min_days` (Themis, 7) days of
  data it says so and stops.
- **Cross-domain links are Athena's job**: Psyche publishes weekly metrics `mood.avg` «Umore medio» and
  `mood.energy` «Energia media»; Athena's reflection already links weekly series of every domain (sleep, training,
  spending…), so «quando dormi poco l'umore scende» comes out there, never as a module reading another module's data.
- **Reflection signals** (`signals_client`, module `psyche`, domain `mood`): `mood_drop` (7-day mean ≥ 1 point under
  the previous 3 weeks), `low_streak` (3+ days in a row with day mood ≤ 2), `energy_low` (3+ days energy ≤ 2),
  `good_streak` (5+ days ≥ 4, milestone). Athena turns them into observations/proposals (e.g. a lighter week); the
  user confirms through Hermes as for every Athena proposal. Psyche never changes plans.
- **Recap piece** «Umore» (recap order 28): done = «Umore 2/5 · stanco», next = a gentle line when a signal is on
  («3 giorni giù: domani vai piano»), action «Come stai?» (opens `mood_log`) when today has no entry.
- **Context for the assistant**: `/api/module/context` (tag `context`) gives Athena/Oracle the last 7 days in one
  line; `when_to_use` lets the classifier pick the `mood` tools when Marko asks how he has been.
- **Check-in**: daily agenda job `psyche.checkin` (20:30, user moves/pauses it in the agenda); it sends one Hermes
  reminder «Com'è andata oggi?» with 3 one-tap buttons only when `psyche.reminder.enabled` (shared
  `hestia_common.reminders`, off by default) and today has no entry.

### 3.6 Clients

- **WebUI plugin «Umore»** (stroke icons, no emoji; new icons `frown`, `meh`, `laugh` added to both icon sets):
  page `umore` = today (5 one-tap faces, energy and stress 1–5, labels and causes chips, note), month calendar
  (one coloured cell per day), trend (mood/energy, 30 days), insights sentences, entries with source (chat shows the
  quote) and delete. **Home widget** «Umore» (today + last 7 days dots) and **quick action** «Come stai?».
- **Telegram**: area «Umore» (😊), tools in the dynamic menu (`telegram_group="umore"`); recap and check-in buttons.
- **External AIs (MCP)**: every `mood_*` tool with the usual read/write scopes.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: remember how he feels without asking, show the history, coach with it.
2. Owner module (R1): Psyche owns mood data; Hygieia keeps its self care diary; Oracle only understands and routes
   (capture); Athena links domains and proposes; Hermes delivers; Chronos schedules the check-in.
3. Configuration (Themis): `psyche.capture.merge_minutes` (120), `psyche.insights.min_days` (7),
   `psyche.reminder.*` (shared helper). No feature switch: capture is how the assistant works.
4. Push/poll: capture pushed by Oracle after the answer; recap pulls the piece; signals pushed on change + daily job.
   Manual = tap, page, Telegram, explicit chat.
5. Who confirms: nobody for a mood (his own words, undoable, visible notice); Athena proposals via Hermes.
6. WebUI (icons, no emoji) and Telegram (tools + display): §3.6.
7. Stop, correct, undo: «non segnarlo», delete in page/Telegram/`mood_delete`; check-in paused in Agenda.
8. Docs that change: `Hestia-Psyche/hestia-psyche.md` (new), Oracle doc (capture), swagger, ARCHITECTURE + flow
   map, AI-GUIDE, Hub tag vocabulary, areas, compose, CI matrix, README module list, root CHANGELOG.

## 5. Phases (one PR)

- **P1** module: data, tools, REST, recap, signals, context, check-in, transfer, Archive store, compose, Hub tags.
- **P2** quiet capture in Oracle: gate + prompt + lexicon fallback + undo + notice; bench of phrases.
- **P3** WebUI plugin page + widget + quick action + icons; Telegram area.
- **P4** docs, swagger, precheck, tests, PR green and merged.

## 6. Acceptance criteria

1. «oggi sono stanco morto» → one `mood` entry (mood ≤ 2 or energy ≤ 2, label stanco, quote, source chat); the reply
   does not claim it; a quiet notice «Umore segnato» follows; it shows in the page and in the recap.
2. «sono stanco, cosa mangio stasera?» → recorded; «perché sono sempre stanco?», «Luca è stanco», «se fossi stanco
   andrei a letto», «non sono stanco», «ciao», «test», «che tempo fa?» → nothing (gate unit bench ≥ 30 phrases).
3. Model offline or answering garbage → the lexicon guess is recorded; model says NONE → nothing.
4. Two captures within 2 h → one entry updated. «non segnarlo» → it is gone, notice «Umore tolto».
5. Tap from Home/page/Telegram → entry with no model call.
6. With ≥ 7 days of data insights speak in plain sentences; with fewer they say how many days are missing.
7. 3 low days → `low_streak` signal; weekly metrics `mood.avg`/`mood.energy` published.
8. Export/import include it; precheck 0 failed; CI green.

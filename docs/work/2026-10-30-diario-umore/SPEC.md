# Diario dell'umore: Hestia remembers how Marko feels, over time, like a coach

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via Project thread (Marko 2026-10-30, in the real-AI test thread: «magari che si ricordi del mio mood e ci sia uno storico tipo coaching non sarebbe male? tipo un modulo diario? questo è una feature nuova separata») |
| **Status** | Draft — waiting for Marko's ok on §3.1 (where it lives) and §3.3 (how the AI records) |

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

### 3.1 Where it lives — DECISION FOR MARKO

| | A. New module «Diario» (recommended) | B. Inside Hygieia |
|---|---|---|
| What | `Hestia-Psyche` (port 19029, store `diary-store`), owns mood check-ins **and the day diary**; the `giornata` spoken diary moves here from Hygieia (with a one-shot migration of existing entries, ids kept) | Hygieia gets area `umore` (metrics umore / energia / stress) and the views below |
| Fits R1 (one module, one job) | Yes: Hygieia stays self care (skin, hair, routines, body-area journal, sleep) | No: mood is not self care; Hygieia grows into "everything about the body and mind" |
| Cost | New module (module_kit makes it ~1 day), migration of `giornata` | Smaller now, harder to untangle later |

Sleep stays in Hygieia (it is a body fact from the watch); the diary only **reads** it for correlations.

### 3.2 Data (Archive `diary-store`, A) — kinds

- `mood` — one check-in: `{id, at, date, mood 1–5, energy 1–5?, stress 1–5?, labels[], causes[], note, quote,
  source: chat|tap|voce|webui|telegram|external, session_id?}`.
  - `labels`: closed vocabulary declared by the module (options), e.g. stanco, carico, sereno, contento, ansioso,
    nervoso, triste, giù, annoiato, motivato, malato. `causes`: lavoro, sonno, persone, salute, sport, soldi, casa,
    tempo libero, meteo.
  - `quote` = Marko's own words (max 200 chars) when it came from chat, so he can see *why* it was recorded.
- `day` — the diary of the day: `{date, text, audio_id?, source}` (today's `giornata`, moved from Hygieia in A).
- Day summary is **computed**, never stored: last mood of the day + min/max + labels union.
- Everything is in `.hestia` export/import and Drive backup through the existing Archive paths (no new path).

### 3.3 How the AI decides what to record — DECISION FOR MARKO (recommended: «quiet capture»)

The model may be a 9B local one, so the rule is small, deterministic where possible, and fails towards NOT recording.

1. **Explicit** («segna che oggi sono giù», «diario: giornata ottima») → tool `diary_log_mood`, normal tool flow, the
   answer may say «Segnato».
2. **Implicit, from chat (quiet capture).** It rides on the post-turn memory extraction that **already runs** (same
   call, no extra cost): the template gets one more output, `{"action":"MOOD","mood":1-5,"energy":1-5|null,
   "labels":[...],"quote":"..."}`, with caveman rules:
   - only the user's **own current state, first person, present/today** («sono stanco», «mi sento uno schifo»,
     «oggi spacco»);
   - a statement inside a request still counts («sono stanco, cosa mangio?»);
   - never: pure questions («perché sono sempre stanco?»), other people, hypotheticals, quotes, tests, jokes he marks as such, past days
     («ieri ero stanco» → only if he says the day, then `date` = yesterday);
   - labels only from the vocabulary; unknown → no label, mood only.
   - **Deterministic guard** in Oracle before saving: the message must contain a first-person state cue (sono, mi
     sento, sto, oggi, stasera…) and at least one word of the label lexicon or a mood word; otherwise the MOOD line
     is dropped (`event=diary_capture_dropped reason=no_cue`). This is what keeps a 9B model honest.
   - **Merge**: a second capture within 2 h of a chat capture updates it instead of adding (Themis
     `diary.capture.merge_minutes`, default 120).
   Oracle then calls the module tool `diary_log_mood` (source `chat`) — the brain only routes what it understood;
   the module owns the data. **The reply never claims it** (it is written after the reply, consistent with the
   truth rule). Marko sees it in the diary, in the recap («Oggi hai detto: stanco») and can remove it.
3. **«Dimentica» / «non segnarlo»** → `diary_delete` (last chat capture of today, or by id). Same verbs that already
   deprecate memories.
4. Rule 2c in memory stays: moods never go to long-term memory; the diary is where they go. A **pattern** («è stanco
   ogni lunedì») is never written to memory by the extractor: it is a computed insight (§3.5).

Alternative (not recommended): ask every time («Lo segno nel diario?») — safe but annoying, and Telegram fills with
confirmations for something worth one tap.

### 3.4 Tools (domain `diary`, Hub tag `diary`, clients ui/telegram/external)

| Tool | What |
|---|---|
| `diary_log_mood` | mood 1–5 (required), energy, stress, labels, causes, note, quote, date, source |
| `diary_today` | today's check-ins + day text |
| `diary_history` | range (default 30 days): per-day summary + entries |
| `diary_delete` | `id` or `last=true` (today's last chat capture) |
| `diary_write_day` | the day's text (typed) |
| `diary_voice` | voice note → Echo (use case `psyche.diario`, recording kept) → day text (replaces `selfcare_diario_voce` in A) |
| `diary_insights` | trend, good/bad days, what goes with them (§3.5), plain sentences |

### 3.5 Coaching (deterministic facts; Oracle only writes words)

- **Trend**: 7/30/90-day average mood and energy, vs the previous period.
- **What goes with it** (computed when ≥ 14 days of data, never with fewer): mean mood on days with/without training
  (Hercules logs), short vs normal sleep (Hygieia `sonno`), rain vs sun (Hecate weather), busy vs free calendar
  (Chronos events count), weekday. Read through Hub read endpoints / feeds — no new links. Phrased as «sembra», never
  as cause.
- **Reflection signals** (`signals_client`, module `psyche`, domain `diary`): `mood_drop` (7-day mean ≥ 1 point under
  the previous 4 weeks), `low_streak` (3+ days mood ≤ 2), `energy_low` (3+ days energy ≤ 2), `good_streak`
  (milestone). Athena (the proposer) turns `energy_low` + a heavy coach week into a proposal «Alleggerisco la
  settimana?»; Marko confirms via Hermes. The diary itself never changes plans.
- **Recap piece** «Diario» (order: one free decade, proposed 170): done = «Umore 2/5 · stanco (alle 14)», actions =
  «Com'è andata?» (1–5 tap) and «Racconta la giornata» until today has a day text.
- **Assistant context**: when Marko talks about how he feels, the classifier picks the `diary` domain and Oracle can
  read `diary_today/history` («ieri eri giù, oggi come va?»). No proactive message outside the recap and the
  check-in.
- **Check-in**: optional daily one-tap question, scheduled as an agenda rule (Chronos) the user edits/pauses; Themis
  `diary.reminder.*` via `hestia_common.reminders` (off by default, max 1 a day). Skipped when the day already has a
  mood.

### 3.6 Clients

- **WebUI plugin page «Diario»** (stroke icons, no emoji, toned colours per mood level): Oggi (5 mood icons + energy
  + labels chips + note), Calendario (month heatmap), Andamento (mood/energy lines 30/90 days, insights sentences),
  Voci (list with source icon chat/tap/voce, quote, edit/delete). **Home quick action** «Come stai?» (5 icons, one tap).
- **Telegram**: menu via the dynamic config (section «Diario»), 1–5 inline buttons from the recap and the check-in,
  voice note for the day. Telegram may keep emoji on the buttons.
- **External AIs (MCP)**: `diary_log_mood`, `diary_history` with write/read scopes as every other tool.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: remember how he feels, show the history, coach with it.
2. Owner module (R1): Psyche (A) owns mood + day diary; Hygieia keeps body/sleep; Oracle only extracts and routes;
   Athena proposes; Hermes delivers; Chronos schedules the check-in.
3. Configuration: Themis `diary.capture.merge_minutes`, `diary.insights.min_days` (14), reminders via
   `hestia_common.reminders`. No switch: the diary is there, used only when wanted (same rule as Hygieia's diary).
4. Push/poll: capture is push from Oracle post-turn; recap pulls the piece; signals pushed on change. Manual = tap,
   page, voice, explicit chat.
5. Who confirms: logging a mood needs no confirmation (it is his own words, undoable); anything that changes plans
   is an Athena proposal confirmed via Hermes; deleting the whole diary asks confirmation via Hermes.
6. WebUI (icons, no emoji) and Telegram (tools + display): §3.6.
7. Stop, correct, undo: «dimentica»/«non segnarlo», delete/edit in the page and Telegram; check-in paused in Agenda.
8. Docs that change: `Hestia-Psyche/hestia-psyche.md` (new), `Hestia-Hygieia/hestia-hygieia.md` (giornata moved),
   Oracle doc (capture), swagger, ARCHITECTURE + flow map, Hub tag vocabulary, compose + `.env.example` comment,
   README module list, root CHANGELOG.

## 5. Phases

- **P1** module + data + tools + migration of `giornata` (A) + recap piece.
- **P2** quiet capture in Oracle (template + deterministic guard + merge + «dimentica»), with a bench of phrases run on
  a small local model and on Gemini (the same style as the real-AI tests).
- **P3** WebUI page + Home quick action + Telegram menu + check-in.
- **P4** insights + signals + Athena proposal.

## 6. Acceptance criteria

1. «oggi sono stanco morto» in chat → one `mood` entry (mood ≤ 2, label stanco, quote kept, source chat); the reply
   does not claim it; it shows in the page and in the evening recap.
2. «sono stanco, cosa mangio stasera?» → recorded; «perché sono sempre stanco?», «Luca è stanco», «se fossi stanco…»,
   «ciao», «test» → nothing recorded (bench of ≥ 30 phrases passes on Gemini and on a 9B local model).
3. Two captures in 2 h → one entry updated. «non segnarlo» → it is gone.
4. Tap 1–5 from Home/Telegram/recap → entry in < 1 s, no model call.
5. Spoken day diary works as today, now in the diary; old `giornata` entries are visible there; Hygieia no longer
   shows them.
6. With ≥ 14 days of data, insights speak in plain sentences and never claim causes; with fewer, they say so.
7. 3 low-energy days → signal; Athena proposes a lighter week; nothing changes until Marko confirms.
8. Export/import and Drive backup include the diary; precheck 0 failed; CI green.

# SPEC — Prima osserva, poi propone; scrive con memoria

| | |
|---|---|
| **Version** | 1.1 |
| **Source** | user via external chat (thread «Rendere Hestia viva come Verity», Marko 2026-11-13: «non deve essere a caso solo per essere a caso… che aspettino di accumulare un po' di dati»; proposal approved with «si») |
| **Status** | Implemented; real run by Marko pending |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).
Follows `docs/work/2026-11-12-identita-e-proattivita` (she writes first).

## 1. Goal
Marko's points after the first PR:
- An assistant started for the first time must not hand out twenty improvement ideas: it cannot know yet whether
  changing a parameter or the code is right. Self-analysis should wait for some days of data; on demand stays.
- Writing first must not be random for the sake of it, and should have more «memory» of today and of the last
  days, so that she has something to talk about, or simply feels like talking.

## 2. What was found in the code
- The life reflection already waits for data (`athena.reflection.min_weeks` closed weeks).
- The system track (`_thinking_cycle`) did not: an `improvement` went to Forge and a `setting` to Themis as soon
  as the relevance gate accepted them, from the first cycle of the first day.
- `talk.py` looked at today only (mood, signals, silence) and chose the minute with a random wait.

## 3. Scope

### A — Evidence before proposing (Athena `core/evidence.py`)
- Applies to candidates of kind `improvement` (→ Forge) and `setting` (→ Themis proposal) of the system track.
- She proposes only when **both** hold:
  1. she has been observing for at least `athena.evidence.min_days` days (default 5) since the first start;
  2. the same finding came up on at least `athena.evidence.seen_days` different days (default 3) within the last
     `athena.evidence.window_days` (default 14, advanced).
- Same finding: a setting = its key; an improvement = titles sharing at least half of their words.
- Until then the candidate is kept with outcome `collecting` and a plain sentence in `gate_reason` («Raccolgo
  prove: visto in 2 giorni su 3 richiesti»); nothing is sent, no hint, no commitment.
- When proposed, the reasoning carries the proof («Visto in 3 giorni diversi dal 10/11») and the count restarts
  from zero, so the same proposal does not come back every day.
- Never wait: faults and notices (`remediation`, `notification`, `advisory`, `maintenance`), and «Pensa ora»
  (the owner asked; the proof so far is still written).
- Ledger in Archive `signals-store` (`kind=evidence`, `ref_id=athena`), so it survives restarts. Ledger not
  readable → nothing is proposed in that cycle (`[🔄]`), never treated as proof.
- `GET /api/athena/evidence` lists what she is collecting.

### B — She writes with memory of the last days (Athena `core/talk.py`, Oracle opener)
- Each of her messages records whether he answered: he wrote after it = yes; 12 hours without a word = no.
- Athena sends Oracle a new list `past` (last 3 days): how he felt each day (Psyche history), what she wrote and
  how it went, and «do not insist» when her last messages got no answer.
- Oracle `POST /api/chat/opener` accepts `past` and shows it as «THE LAST DAYS».

### C — A drive to talk instead of chance
- No random wait anywhere. Her drive (0–1) is computed from the state:
  - grows with the silence between them (full after 36 hours);
  - grows with what is true to say today (mood, signals; two things = full);
  - +0.10 when he answered her last message, −0.25 for each of her last messages left unanswered;
  - damped in the first days (from half on day 0 to full after 7 days of observation).
- She writes when the drive reaches the bar of `athena.talk.eagerness` («Quanto è loquace», 1–5, default 3).
  The drive is weighed again every 30 minutes. `max_per_day`, `min_gap_hours`, the agenda window and «never while
  he is chatting» stay as caps.
- `GET /api/athena/talk` adds `state` (drive, bar, reasons, last days) and, per message, `drive` and `answered`.

### D — Where the owner sees it (v1.1, Marko: «useful, but not too many pages; look for a fitting place»)
No new page: both go in the existing page **Pensieri** of Athena.
- Tab Sistema, new card «Sta raccogliendo prove»: the days of observation so far, and each finding with on how
  many days it was seen out of the days needed.
- Third tab «Ti scrive»: her drive now against the bar, the reasons of today, what she wrote in the last 14 days
  with why and whether you answered, and the button «Scrivimi ora».
- `GET /api/athena/talk` returns the reasons in Italian for the owner and no longer the hidden `past` lines.

## 4. Out of scope
- The life reflection and the evening recap are unchanged.

## 5. Acceptance criteria
- [x] First start: no improvement or setting proposal during the observation days; faults still reported.
- [x] A finding seen once is kept as `collecting`; proposed on the third different day with the proof in the text.
- [x] «Pensa ora» proposes at once.
- [x] Same state gives the same decision to write (no randomness); first day she does not write by herself.
- [x] Unanswered messages lower the drive and reach Oracle as «do not insist».
- [x] Unit tests for A, B, C; Athena and Oracle suites green.
- [x] D: bundle builds, typechecks, rendered with mocked data at desktop and phone width.

## 6. New-feature checklist
- Settings in Themis (`athena.evidence.*`, `athena.talk.eagerness`), no env var, no on/off switch.
- Hub only; Oracle writes, Hermes delivers, Archive stores. No new timers: the existing loop tick.
- Hidden text to the model in English; texts shown to the owner in Italian.

# Hestia-Psyche 🙂

**Role:** How the owner feels over time («Umore») — mood, energy and stress check-ins, written down by a tap or
quietly by the assistant when he says how he feels in chat; trend, insights and signals like a coach
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19029 · Dossier: `docs/work/2026-10-30-diario-umore/` (SPEC v2.0)

---

## Responsibility

- Check-ins in Archive `mood-store`, kind `mood` (`ref_id` = local date): `mood` 1–5 (required), `energy` and
  `stress` 1–5, `labels` (stanco, carico, sereno, contento, motivato, annoiato, nervoso, ansioso, triste, giù,
  arrabbiato, malato), `causes` (lavoro, sonno, persone, salute, sport, soldi, casa, tempo libero, meteo), `note`,
  `quote` (the owner's own words when it came from chat), `source` (`chat | tap | webui | telegram | external |
  checkin`). Words outside the vocabulary are dropped; future dates refused.
- **Quiet capture** (capability `mood_capture_endpoint` = `/api/mood/capture`): Oracle sends what it understood from
  a chat message after the answer, with no confirmation (Marko 2026-10-30: «l'assistente deve essere
  intelligente»). A capture within `psyche.capture.merge_minutes` (default 120) of today's previous chat capture
  updates it (labels and causes joined, quotes joined) instead of adding a row. `POST /api/mood/capture/undo`
  («non segnarlo») removes today's last chat capture; taps and manual entries are never touched by it.
- Everything derived is computed here, deterministically (no model): day summary (the last check-in of the day
  wins, plus min/max and every label), history, insights in plain sentences (30 days vs the 30 before, energy, best
  and worst weekday over 90 days, frequent words, causes that come back on bad and good days — «sembra», never a
  cause; fewer than `psyche.insights.min_days`, default 7, days → it says how many are missing).
- **Reflection** (`signals_client`, module `psyche`, domain `mood`): signals `mood_drop` (7-day mean ≥ 1 under the
  3 weeks before), `low_streak` (3+ days mood ≤ 2), `energy_low` (3+ days energy ≤ 2), `good_streak` (5+ days ≥ 4,
  milestone); weekly metrics `mood.avg` «Umore medio» and `mood.energy` «Energia media». Athena links them with the
  other domains' weekly series (sleep, training, spending…): Psyche never reads another module's data.
- **Recap** piece «Umore» (order 28): today's mood and words; a gentle line when energy or mood has been low for 3+
  days; action «Come stai?» (opens `mood_log`) while today has nothing.
- **Check-in**: agenda job `psyche.checkin` (20:30, the owner moves or pauses it in the agenda) sends one Hermes
  question «Com'è andata oggi?» with «Giù / Così così / Bene» only when `psyche.reminder.enabled` (shared
  `hestia_common.reminders`, off by default) and today has no check-in. Agenda job `psyche.signals` (17:30).
- Context contract (tag `context`): `GET /api/module/context` = the last 7 days in one line (`topic=insights` →
  the insights sentences).
- Export/import section `umore`.

## Settings (Themis)

`psyche.capture.merge_minutes` (120), `psyche.insights.min_days` (7), `psyche.reminder.enabled` (false),
`psyche.reminder.max_per_week` (7).

## API (`/api/mood`)

`GET/POST /api/mood` (`days`) · `POST /tap` · `GET /today` · `GET /history` · `GET /insights` · `GET /options` ·
`POST /capture` · `POST /capture/undo` · `POST /signals/run` (agenda) · `POST /checkin` (agenda) ·
`PUT/DELETE /{id}` · `GET /api/module/context` · `GET /api/module/recap`.

## Tools (Telegram area «Umore»)

`mood_log` (only when the owner asks; chat phrases are captured on their own), `mood_today`, `mood_history`,
`mood_insights`, `mood_delete` (`id` or `last=true`). Clients `telegram`, `ui`, `external`.

## WebUI plugin

Page **Umore** (`psyche-mood`): five faces (one tap saves; «Dettagli» adds energy, stress, words, causes and a
note), the last 5 weeks as coloured cells, the trend chart with the insights, every entry with its source (chat
shows the quote) and «Togli». Widget «Umore» (`psyche-widget`, s/m): today's face or three one-tap faces, the last
7 days. Quick action «Come stai?» (`POST /api/mood/tap`). Icons `frown`, `meh`, `smile`, `laugh` (no emoji).

## Tests

`Hestia-Psyche/tests/test_psyche.py` and `tests/test_webui_plugin.py` (FakeArchive, no network). The capture gate
and prompt are tested in `Hestia-Oracle/tests/test_mood_capture.py`.

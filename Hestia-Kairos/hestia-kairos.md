# Hestia-Kairos ⏳

**Role:** Deadlines («Scadenze») — bills, insurance, car tax, inspection, servicing, documents, subscriptions, taxes:
due day, amount, recurrence, lead time and a practical advice
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19028 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5, brainstorm B7)

---

## Responsibility

- Deadlines in Archive `deadlines-store` (kind `deadline`, status `open | proposed | done | dismissed`).
- Categories with a default lead time and advice (`GET /api/deadlines/categories`); the category is guessed from the
  title when not given. A better advice is written on request by the assistant (Oracle use case
  `kairos.consiglio`, chain `veloce`; offline → the category advice stays).
- **Recurrence** (`monthly … biennial`): «Fatto» rolls the deadline to the next due day (end of month safe); one-off
  deadlines close.
- Every open deadline is mirrored in the calendar as an agenda event `kairos.<id>` (09:00 of the day), updated on
  change, marked done or cancelled with it.
- **Mail by push** (Iris subscription `kairos:mail`, subject words = Themis setting `kairos.mail.words`): a mail
  that talks about a deadline **and** names a clear future date becomes a `proposed` deadline and a Hermes card
  «Nuova scadenza?» with «Aggiungi» / «No». Nothing enters the calendar before the owner confirms. Each mail once.
- Agenda job `kairos.daily` (08:30): one notice at the lead time and one on the day, with «Fatto» and
  «Fra 3 giorni» (snooze: reminds again after the pause); a stage is notified once per due day.
- Recap piece «Scadenze» (next 7 days). Export/import section `scadenze`.

## API (`/api/deadlines`)

`GET/POST /api/deadlines` (`status`, `days`, `category`) · `GET /categories` · `GET/PUT/DELETE /{id}` ·
`POST /{id}/done|snooze|confirm|dismiss` · `POST /daily` (agenda) · `POST /mail` (Iris doorbell).

## Tools (Telegram area «Scadenze»)

`scadenze_list`, `scadenze_get`, `scadenze_add`, `scadenze_update`, `scadenze_done`, `scadenze_snooze`,
`scadenze_delete`, `scadenze_consiglio`.

## WebUI plugin

Pages **Scadenze** (`kairos-list`: proposals from mail to confirm or dismiss, next 30 days, later, done; «Fatto», «Dopo», new deadline) and **Scadenza** (`scadenza/:id`: edit, advice, delete); widget «Scadenze» (only the deadlines: title and link to the page are the frame's). Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Kairos/tests/test_kairos.py` and `tests/test_webui_plugin.py` (FakeArchive + fake agenda, no network).

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: The Scadenze widget calls `markEmpty()` when there is no deadline, so the Home cell shrinks.

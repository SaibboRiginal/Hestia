# Hestia-Kairos ⏳

**Role:** Deadlines («Deadlines») — bills, insurance, car tax, inspection, servicing, documents, subscriptions, taxes:
due day, amount, recurrence, lead time and a practical advice
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19028 · Dossier: `docs/work/2026-10-24-whole-cindy-brainstorm/` (W5, brainstorm B7)

---

## Responsibility

- Deadlines in Archive `deadlines-store` (kind `deadline`, status `open | proposed | done | dismissed`).
- Categories with a default lead time and advice (`GET /api/deadlines/categories`); the category is guessed from the
  title when not given. A better advice is written on request by the assistant (Oracle use case
  `kairos.advice`, chain `fast`; offline → the category advice stays).
- **Recurrence** (`monthly … biennial`): «Done» rolls the deadline to the next due day (end of month safe); one-off
  deadlines close.
- Every open deadline is mirrored in the calendar as an agenda event `kairos.<id>` (09:00 of the day), updated on
  change, marked done or cancelled with it.
- **Mail by push** (Iris subscription `kairos:mail`, subject words = Themis setting `kairos.mail.words`): a mail
  that talks about a deadline **and** names a clear future date becomes a `proposed` deadline and a Hermes card
  «New deadline?» with «Add» / «no». Nothing enters the calendar before the owner confirms. Each mail once.
- Agenda job `kairos.daily` (08:30): one notice at the lead time and one on the day, with «Done» and
  «In 3 days» (snooze: reminds again after the pause); a stage is notified once per due day.
- Recap piece «Deadlines» (next 7 days). Export/import section `deadlines`.

## API (`/api/deadlines`)

`GET/POST /api/deadlines` (`status`, `days`, `category`) · `GET /categories` · `GET/PUT/DELETE /{id}` ·
`POST /{id}/done|snooze|confirm|dismiss` · `POST /daily` (agenda) · `POST /mail` (Iris doorbell).

## Tools (Telegram area «Deadlines»)

`deadlines_list`, `deadlines_get`, `deadlines_add`, `deadlines_update`, `deadlines_done`, `deadlines_snooze`,
`deadlines_delete`, `deadlines_advice`.

## WebUI plugin

Pages **Scadenze** (place `agenda`: in the Agenda panel; `kairos-list`: proposals from mail to confirm or dismiss, next 30 days, later, done; «Done», «After», new deadline) and **Scadenza** (`deadline/:id`: edit, advice, delete); widget «Deadlines» (only the deadlines: title and link to the page are the frame's). Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Kairos/tests/test_kairos.py` and `tests/test_webui_plugin.py` (FakeArchive + fake agenda, no network).

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-frontend-review-and-tests`)**: The Scadenze widget calls `markEmpty()` when there is no deadline, so the Home cell shrinks.


**2026-11-14 (backend English, dossier `docs/work/2026-11-14-english-backend`)**: tool descriptions, the module manual and the advice prompt are English; the advice is written in the owner's language. What people read about the tools comes from `hestia_common/locales/<lang>/tools.json`.

**2026-11-15 (owner's language, dossier `docs/work/2026-11-14-english-backend`)**: the notices, errors and cards this module shows go through `hestia_common.i18n.t` and follow «Language».

**2026-11-15 (WebUI page in the owner's language, dossier `docs/work/2026-11-14-english-backend`)**: the texts of this module's WebUI page and widgets go through `tr` of `@hestia/webui-sdk` and follow «Language»; source texts in English, Italian in `Hestia-Shared/hestia_common/locales/it/messages.json`.

**2026-11-16 (no Italian in the code, dossier `docs/work/2026-11-14-english-backend` v2.0)**: every text is English in the code; Italian lives only in `Hestia-Shared/hestia_common/locales/it/messages.json`. Labels declared at registration (manifest, capabilities, agenda rules, settings) are plain English, translated at the edge.

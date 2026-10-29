# Hestia-Hera 👥

**Role:** Important people («Persone») — a card per person: relation, birthday and other dates, likes and dislikes,
gift ideas, notes, last contact and how often to hear from them
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19025 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5, brainstorm A4)

---

## Responsibility

- Cards in Archive `people-store` (kinds `person`, `interaction`). Search by id or by name (exact, then partial;
  more than one match → a clear «più persone corrispondono» error).
- Every date of a card becomes a yearly **special event** in the calendar: `POST /route/chronos/api/special` with the
  stable key `hera-<person id>-<n>` and `by: "hera"`, so the owner's edits in the calendar win. Lead time per date
  (default 7 days); the calendar sends the lead notice and the greeting.
- On the day the calendar pushes `special_moment` (capability `special_moment_endpoint` = `/api/people/moment`):
  Hera answers with a Hermes notice of the gift ideas still open («Idee per Anna»).
- `contact_every_days`: the agenda job `hera.daily` (18:00, user-editable in the agenda) sends one «Senti …?»
  notice per person due a call, with the action «Sentito» (`POST /api/people/{id}/contact`); `replaces` keeps one.
- The assistant saves what it hears in conversations: `people_gift_idea`, `people_like` (dedup case-insensitive).
- Recap piece «Persone» (dates of the next days). Export/import sections `persone`, `contatti`.
- Never talks to the owner directly (Hermes), never calls models.

## API (`/api/people`)

`GET/POST /api/people` · `GET /upcoming?days=` · `GET/PUT/DELETE /{id}` · `POST /{id}/contact {note?, date?}` ·
`POST /moment` (calendar push) · `POST /daily` (agenda job). Tools also as REST under `/api/people/tools/<name>`. For the WebUI page:
`POST /{id}/gift {idea}` · `POST /{id}/gift/{gift_id}/done` · `POST /{id}/like {text, dislike?}`.

## Tools (Telegram area «Persone»)

`people_list`, `people_get`, `people_add`, `people_update` (`date_label` + `date_day` add a date), `people_delete`,
`people_gift_idea`, `people_like`, `people_contact`, `people_upcoming`. Dates: `GG/MM`, `GG/MM/AAAA`, `AAAA-MM-GG`;
a day that does not exist (31/02) is refused; 29/02 falls on 28/02 in common years.

## WebUI plugin

Pages **Persone** (`hera-people`: list, search, new person, upcoming dates) and **Persona** (`persona/:id`: dates, gift ideas to mark done, likes, notes, «Sentito», delete); widget «Prossime date» (only the dates: title and link to the page are the frame's). Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Hera/tests/test_hera.py` and `tests/test_webui_plugin.py` (FakeArchive, no network).
